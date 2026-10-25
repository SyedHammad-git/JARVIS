'use strict';

const os = require('node:os');
const { spawn: defaultSpawn } = require('node:child_process');

const APP_ALLOWLIST = Object.freeze({
  notepad: 'notepad.exe',
  calculator: 'calc.exe',
  explorer: 'explorer.exe',
  paint: 'mspaint.exe',
});

const HIGH_RISK_ACTIONS = Object.freeze(['lock_screen']);
const REPLAY_WINDOW_MS = 5 * 60 * 1000;
const MAX_COMMAND_AGE_MS = 60 * 1000;

function cleanString(value, maxLength) {
  if (typeof value !== 'string') return null;
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, '').trim();
  return cleaned && cleaned.length <= maxLength ? cleaned : null;
}

function hasOnlyKeys(value, allowed) {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function launchDetached(spawn, executable, args = []) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let child;
    try {
      child = spawn(executable, args, { shell: false, detached: true, windowsHide: true, stdio: 'ignore' });
    } catch (error) {
      reject(error);
      return;
    }
    child.once('error', (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    });
    child.once('spawn', () => {
      if (settled) return;
      settled = true;
      child.unref();
      resolve();
    });
  });
}

function createExecutor({ shell, Notification, cameraSnapshot, spawn = defaultSpawn, osModule = os }) {
  async function execute(action, args) {
    if (typeof action !== 'string' || !Object.hasOwn(handlers, action)) {
      return { ok: false, error: 'unknown_action' };
    }
    if (!args || typeof args !== 'object' || Array.isArray(args)) {
      return { ok: false, error: 'invalid_arguments' };
    }
    try {
      return await handlers[action](args);
    } catch {
      return { ok: false, error: 'action_failed' };
    }
  }

  const handlers = {
    async open_app(args) {
      if (!hasOnlyKeys(args, ['target'])) return { ok: false, error: 'invalid_arguments' };
      const target = cleanString(args.target, 40)?.toLowerCase();
      if (!target) return { ok: false, error: 'invalid_arguments' };
      const executable = APP_ALLOWLIST[target];
      if (!executable) return { ok: false, error: `app_not_allowed: ${target.slice(0, 40)}` };
      await launchDetached(spawn, executable);
      return { ok: true, message: `Opened ${target}` };
    },
    async open_url(args) {
      if (!hasOnlyKeys(args, ['url'])) return { ok: false, error: 'invalid_arguments' };
      const rawUrl = cleanString(args.url, 2048);
      if (!rawUrl) return { ok: false, error: 'invalid_arguments' };
      let url;
      try {
        url = new URL(rawUrl);
      } catch {
        return { ok: false, error: 'invalid_url' };
      }
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
        return { ok: false, error: 'invalid_url' };
      }
      await shell.openExternal(url.toString());
      return { ok: true, message: 'Opened URL' };
    },
    async notify(args) {
      if (!hasOnlyKeys(args, ['title', 'body'])) return { ok: false, error: 'invalid_arguments' };
      const title = cleanString(args.title, 80);
      const body = cleanString(args.body, 300);
      if (!title || !body) return { ok: false, error: 'invalid_arguments' };
      if (!Notification || !Notification.isSupported()) return { ok: false, error: 'notifications_unavailable' };
      const notification = new Notification({ title, body });
      notification.show();
      return { ok: true, message: 'Notification shown' };
    },
    async take_snapshot(args) {
      if (!hasOnlyKeys(args, ['question', 'width', 'quality'])) return { ok: false, error: 'invalid_arguments' };
      if (args.question !== undefined && (typeof args.question !== 'string' || args.question.length > 500)) {
        return { ok: false, error: 'invalid_arguments' };
      }
      if (!cameraSnapshot) return { ok: false, error: 'camera_disabled' };
      const snapshot = await cameraSnapshot({
        width: args.width ?? 640,
        quality: args.quality ?? 0.7,
        question: args.question || '',
      });
      if (snapshot?.ok === false) return snapshot;
      return { ok: true, ...snapshot };
    },
    async lock_screen(args) {
      if (Object.keys(args).length) return { ok: false, error: 'invalid_arguments' };
      await launchDetached(spawn, 'rundll32.exe', ['user32.dll,LockWorkStation']);
      return { ok: true, message: 'Screen locked' };
    },
    async system_stats(args) {
      if (Object.keys(args).length) return { ok: false, error: 'invalid_arguments' };
      return {
        ok: true,
        load: osModule.loadavg(),
        memory: { totalBytes: osModule.totalmem(), freeBytes: osModule.freemem() },
        uptimeSeconds: osModule.uptime(),
      };
    },
  };

  return { execute };
}

function parseTimestamp(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value < 1e12 ? value * 1000 : value;
  }
  if (typeof value === 'string' && value.length <= 40) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function summarizeArgs(action, args) {
  if (action === 'open_app') {
    return { target: typeof args.target === 'string' ? args.target.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 40) : '[invalid]' };
  }
  if (action === 'open_url') {
    try {
      const url = new URL(args.url);
      return { protocol: url.protocol, host: url.host.slice(0, 120) };
    } catch {
      return { url: '[invalid]' };
    }
  }
  if (action === 'notify') {
    return { title: typeof args.title === 'string' ? args.title.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 80) : '[invalid]' };
  }
  if (action === 'take_snapshot') {
    return { width: args.width ?? 640, quality: args.quality ?? 0.7 };
  }
  return {};
}

function summarizeResult(action, result) {
  if (action !== 'take_snapshot') return result;
  return { ok: result?.ok === true, error: result?.error, mime: result?.mime };
}

function createCommandHandler({ execute, isRemoteEnabled, audit, now = Date.now }) {
  const seen = new Map();

  async function handle(command) {
    const instant = now();
    for (const [id, acceptedAt] of seen) {
      if (instant - acceptedAt >= REPLAY_WINDOW_MS) seen.delete(id);
    }
    let action = typeof command?.action === 'string' ? command.action.slice(0, 64) : 'unknown';
    const args = command?.args && typeof command.args === 'object' && !Array.isArray(command.args) ? command.args : {};
    let result;
    const id = command && typeof command.id === 'string' ? command.id : '';

    if (!id || id.length > 128 || /[\u0000-\u001f]/.test(id)) {
      result = { ok: false, error: 'invalid_command' };
    } else if (command.timestamp !== undefined) {
      const timestamp = parseTimestamp(command.timestamp);
      if (timestamp === null || timestamp < instant - MAX_COMMAND_AGE_MS || timestamp > instant + MAX_COMMAND_AGE_MS) {
        result = { ok: false, error: 'stale_command' };
      }
    }

    if (!result && seen.has(id)) result = { ok: false, error: 'replayed_command' };
    if (!result) {
      seen.set(id, instant);
      if (!isRemoteEnabled()) result = { ok: false, error: 'remote_disabled' };
      else result = await execute(action, args);
    }

    try {
      audit.write({ action, args: summarizeArgs(action, args), result: summarizeResult(action, result) });
    } catch {
      // Audit failures must not suppress the protocol acknowledgement.
    }
    return result;
  }

  return { handle, seen };
}

module.exports = {
  APP_ALLOWLIST,
  HIGH_RISK_ACTIONS,
  MAX_COMMAND_AGE_MS,
  REPLAY_WINDOW_MS,
  cleanString,
  createCommandHandler,
  createExecutor,
  parseTimestamp,
  summarizeArgs,
  summarizeResult,
};
