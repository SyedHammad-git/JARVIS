'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { APP_ALLOWLIST, createCommandHandler, createExecutor } = require('../src/executor');
const { createApproval } = require('../src/approval');
const { createStore, validateConfig } = require('../src/store');
const { createAudit } = require('../src/audit');
const { createRevocationMonitor, isRevokedConnectError, isUnauthorizedConnectError } = require('../src/revocation');
const { redeemPairCode, validateBackendUrl } = require('../src/pairing');

test('pairing redeems a short-lived code and validates the backend URL', async () => {
  assert.equal(validateBackendUrl('http://localhost:5000', true), 'http://localhost:5000');
  assert.throws(() => validateBackendUrl('http://example.test'), /insecure_url/);
  const calls = [];
  const config = await redeemPairCode(
    { url: 'https://backend.example.test', code: 'abc234de' },
    async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({ device_id: 'device-1', token: 'one-time-token' }), { status: 200 });
    },
  );
  assert.deepEqual(config, {
    url: 'https://backend.example.test',
    deviceId: 'device-1',
    token: 'one-time-token',
  });
  assert.equal(calls[0].url, 'https://backend.example.test/pairing/redeem-code');
  assert.deepEqual(JSON.parse(calls[0].options.body), { code: 'ABC234DE', name: 'PC' });
  assert.throws(() => validateBackendUrl('https://backend.example.test/path'), /insecure_url/);
});

test('executor launches only allowlisted apps with shell disabled', async () => {
  const calls = [];
  const executor = createExecutor({
    shell: { openExternal: async () => {} },
    Notification: null,
    spawn: (exe, args, options) => {
      calls.push({ exe, args, options });
      const child = new EventEmitter();
      child.unref = () => {};
      process.nextTick(() => child.emit('spawn'));
      return child;
    },
  });
  assert.deepEqual(Object.keys(APP_ALLOWLIST).sort(), ['calculator', 'explorer', 'notepad', 'paint']);
  assert.deepEqual(await executor.execute('open_app', { target: 'notepad' }), { ok: true, message: 'Opened notepad' });
  assert.equal(calls[0].exe, 'notepad.exe');
  assert.equal(calls[0].options.shell, false);
  assert.equal(calls[0].options.detached, true);
  assert.deepEqual(await executor.execute('open_app', { target: 'regedit' }), { ok: false, error: 'app_not_allowed: regedit' });
  assert.deepEqual(await executor.execute('open_app', { target: 'notepad', args: ['x'] }), { ok: false, error: 'invalid_arguments' });
  assert.deepEqual(await executor.execute('unknown', {}), { ok: false, error: 'unknown_action' });
});

test('executor validates URL, notification strings, and argument shapes', async () => {
  const opened = [];
  const notices = [];
  class FakeNotification {
    static isSupported() { return true; }
    constructor(options) { notices.push(options); }
    show() {}
  }
  const executor = createExecutor({
    shell: { openExternal: async (url) => opened.push(url) },
    Notification: FakeNotification,
  });
  assert.equal((await executor.execute('open_url', { url: 'javascript:alert(1)' })).error, 'invalid_url');
  assert.equal((await executor.execute('open_url', { url: 'https://user:pass@example.com' })).error, 'invalid_url');
  assert.equal((await executor.execute('open_url', { url: 'https://example.com' })).ok, true);
  assert.equal(opened[0], 'https://example.com/');
  assert.equal((await executor.execute('notify', { title: 'x'.repeat(81), body: 'ok' })).error, 'invalid_arguments');
  assert.equal((await executor.execute('notify', { title: 'Ready', body: 'Done' })).ok, true);
  assert.deepEqual(notices[0], { title: 'Ready', body: 'Done' });
  assert.equal((await executor.execute('system_stats', [])).error, 'invalid_arguments');
});

test('command handler rejects malformed, stale, replayed, and kill-switch commands', async () => {
  let instant = 1_800_000_000_000;
  let enabled = true;
  const executed = [];
  const audited = [];
  const guard = createCommandHandler({
    execute: async (action, args) => { executed.push({ action, args }); return { ok: true }; },
    isRemoteEnabled: () => enabled,
    audit: { write: (entry) => audited.push(entry) },
    now: () => instant,
  });
  assert.equal((await guard.handle({ id: 4, action: 'open_app', args: {} })).error, 'invalid_command');
  assert.equal((await guard.handle({ id: 'old', timestamp: instant - 61_000, action: 'open_app' })).error, 'stale_command');
  enabled = false;
  assert.equal((await guard.handle({ id: 'disabled', action: 'open_app', args: {} })).error, 'remote_disabled');
  enabled = true;
  const fresh = { id: 'fresh', action: 'open_app', args: { target: 'notepad' } };
  assert.deepEqual(await guard.handle(fresh), { ok: true });
  assert.equal((await guard.handle(fresh)).error, 'replayed_command');
  instant += 5 * 60 * 1000;
  assert.deepEqual(await guard.handle(fresh), { ok: true });
  assert.equal(executed.length, 2);
  assert.equal(audited.length, 6);
});

test('pairing URLs require HTTPS except development loopback', () => {
  assert.equal(validateConfig({ url: 'https://jarvis.example.com', deviceId: 'd1', token: 'secret' }).url, 'https://jarvis.example.com');
  assert.equal(validateConfig({ url: 'http://localhost:5000', deviceId: 'd1', token: 'secret' }, true).url, 'http://localhost:5000');
  assert.throws(() => validateConfig({ url: 'http://example.com', deviceId: 'd1', token: 'secret' }, true), /insecure_url/);
  assert.throws(() => validateConfig({ url: 'https://u:p@example.com', deviceId: 'd1', token: 'secret' }), /insecure_url/);
});

test('credential store encrypts persisted data and audit omits token fields', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'jarvis-client-'));
  const previousDevMode = process.env.JARVIS_DEV;
  process.env.JARVIS_DEV = '1';
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(Buffer.from(value, 'utf8').toString('base64'), 'utf8'),
    decryptString: (value) => Buffer.from(value.toString('utf8'), 'base64').toString('utf8'),
  };
  try {
    const store = createStore({ app: { getPath: () => directory }, safeStorage });
    const credentials = { url: 'http://localhost:5000', deviceId: 'device-1', token: 'never-store-plain' };
    store.save(credentials);
    const persisted = fs.readFileSync(store.filePath, 'utf8');
    assert.equal(persisted.includes(credentials.token), false);
    assert.equal(persisted.includes('"token"'), false);
    assert.deepEqual(store.load(), credentials);

    const audit = createAudit({ app: { getPath: () => directory } });
    audit.write({ action: 'open_app', args: { target: 'notepad', token: credentials.token }, result: { ok: true } });
    const line = fs.readFileSync(audit.filePath, 'utf8');
    assert.equal(line.includes(credentials.token), false);
    assert.equal(line.includes('"token"'), false);
    store.clear();
    assert.equal(store.load(), null);
  } finally {
    if (previousDevMode === undefined) delete process.env.JARVIS_DEV;
    else process.env.JARVIS_DEV = previousDevMode;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('offline status keeps retrying, explicit revoked status stops the monitor', async () => {
  const scheduled = [];
  let scheduledCount = 0;
  let revoked = 0;
  let requestUrl;
  const responses = [
    { execution_mode: 'remote', online: false, revoked: false },
    { execution_mode: 'remote', online: false, revoked: true },
  ];
  const socket = { connected: true };
  let tokenPresent = true;
  const authorizationStates = [];
  const monitor = createRevocationMonitor({
    fetchImpl: async (url) => {
      requestUrl = url.toString();
      return { ok: true, status: 200, json: async () => responses.shift() };
    },
    setTimer: (callback, delay) => {
      assert.equal(delay, 15_000);
      scheduled.push(callback);
      scheduledCount += 1;
      return scheduledCount;
    },
    clearTimer: () => {},
  });
  monitor.start({ url: 'http://localhost:5000', deviceId: 'device-1' }, socket, (state) => {
    authorizationStates.push(state);
    if (state === 'revoked') {
      tokenPresent = false;
      revoked += 1;
      socket.connected = false;
    }
  });
  await scheduled[0]();
  assert.match(requestUrl, /\/api\/device\/status\?device_id=device-1$/);
  assert.equal(revoked, 0);
  assert.equal(socket.connected, true);
  assert.equal(scheduledCount, 2);
  await scheduled[1]();
  assert.deepEqual(authorizationStates, ['revoked']);
  assert.equal(revoked, 1);
  assert.equal(tokenPresent, false);
  assert.equal(socket.connected, false);
  assert.equal(scheduledCount, 2);
});

test('401 and 403 stop monitoring but retain credentials for manual retry', async () => {
  for (const status of [401, 403]) {
    const scheduled = [];
    let state;
    const monitor = createRevocationMonitor({
      fetchImpl: async () => ({ status, ok: false }),
      setTimer: (callback) => { scheduled.push(callback); return scheduled.length; },
      clearTimer: () => {},
    });
    const credentials = { token: 'still-encrypted' };
    monitor.start({ url: 'https://jarvis.example.com', deviceId: 'device-1' }, { connected: true }, (value) => {
      state = value;
      if (value === 'revoked') credentials.token = '';
    });
    await scheduled[0]();
    assert.equal(state, 'reauthentication');
    assert.equal(credentials.token, 'still-encrypted');
    assert.equal(scheduled.length, 1);
  }
  assert.equal(isUnauthorizedConnectError({ status: 401 }), true);
  assert.equal(isUnauthorizedConnectError({ data: { status: 403 } }), true);
  assert.equal(isRevokedConnectError({ data: { error: 'device_revoked' } }), true);
  assert.equal(isRevokedConnectError({ message: 'device_revoked' }), false);
  assert.equal(isRevokedConnectError(new Error('temporary_network_error')), false);
});

test('status endpoint outage keeps the revocation monitor retrying', async () => {
  const scheduled = [];
  let revoked = false;
  const monitor = createRevocationMonitor({
    fetchImpl: async () => { throw new Error('backend_unavailable'); },
    setTimer: (callback) => { scheduled.push(callback); return scheduled.length; },
    clearTimer: () => {},
  });
  monitor.start({ url: 'https://jarvis.example.com', deviceId: 'device-1' }, { connected: false }, () => {
    revoked = true;
  });
  await scheduled[0]();
  assert.equal(revoked, false);
  assert.equal(scheduled.length, 2);
  monitor.stop();
});

test('status endpoint 5xx keeps the revocation monitor retrying', async () => {
  const scheduled = [];
  const monitor = createRevocationMonitor({
    fetchImpl: async () => ({ status: 503, ok: false }),
    setTimer: (callback) => { scheduled.push(callback); return scheduled.length; },
    clearTimer: () => {},
  });
  monitor.start({ url: 'https://jarvis.example.com', deviceId: 'device-1' }, { connected: true }, () => {
    assert.fail('5xx response must not signal revocation or re-authentication');
  });
  await scheduled[0]();
  assert.equal(scheduled.length, 2);
  monitor.stop();
});

test('approval only prompts for high-risk actions and times out as deny', async () => {
  let timerCallback;
  const approval = createApproval({
    dialog: { showMessageBox: () => new Promise(() => {}) },
    timeoutMs: 30_000,
    setTimer: (callback, duration) => { assert.equal(duration, 30_000); timerCallback = callback; return 1; },
    clearTimer: () => {},
  });
  assert.equal(await approval.request('open_app'), false);
  const pending = approval.request('shutdown', { summary: 'Power off' });
  timerCallback();
  assert.equal(await pending, false);
});

test('approval accepts only the explicit Approve response', async () => {
  const approval = createApproval({ dialog: { showMessageBox: async () => ({ response: 0 }) } });
  assert.equal(await approval.request('restart'), true);
});

test('snapshot executor returns a valid acknowledged image payload', async () => {
  const executor = createExecutor({
    shell: { openExternal: async () => {} },
    Notification: null,
    cameraSnapshot: async (options) => {
      assert.deepEqual(options, { width: 640, quality: 0.7, question: 'Describe this.' });
      return { image_b64: 'AQID', mime: 'image/jpeg' };
    },
  });
  assert.deepEqual(await executor.execute('take_snapshot', { question: 'Describe this.' }), {
    ok: true,
    image_b64: 'AQID',
    mime: 'image/jpeg',
  });
});
