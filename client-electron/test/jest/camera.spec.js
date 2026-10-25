'use strict';

const { EventEmitter } = require('node:events');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { CAPTURE_CHANNEL, createCamera } = require('../../src/camera');
const { denyWindowPermissions } = require('../../src/window-security');
const { loadPreferences, persistedPreferences } = require('../../src/preferences');

function cameraHarness({ allowed = true, now = () => 10_000 } = {}) {
  const ipcMain = new EventEmitter();
  const audit = { write: jest.fn() };
  const notification = { show: jest.fn() };
  const permission = { request: null };
  const pagePath = path.join(__dirname, 'camera-capture.html');
  const pageUrl = pathToFileURL(pagePath).href;
  const calls = { permissionResults: [], destroyed: 0, loaded: 0 };
  const captureData = `data:image/jpeg;base64,${Buffer.from('jpeg').toString('base64')}`;

  class FakeWindow {
    constructor(options) {
      this.options = options;
      this.webContents = { getURL: () => pageUrl };
    }
    async loadFile() {
      calls.loaded += 1;
      for (const url of [pageUrl, 'https://example.invalid/camera-capture.html']) {
        permission.request(this.webContents, 'media', (granted) => calls.permissionResults.push(granted), { requestingUrl: url });
      }
      permission.request(this.webContents, 'camera', (granted) => calls.permissionResults.push(granted), { requestingUrl: pageUrl });
      ipcMain.emit(CAPTURE_CHANNEL, { sender: {} }, { dataUrl: captureData });
      ipcMain.emit(CAPTURE_CHANNEL, { sender: this.webContents }, { dataUrl: captureData });
    }
    isDestroyed() { return calls.destroyed > 0; }
    destroy() { calls.destroyed += 1; }
  }

  const captureSession = {
    setPermissionRequestHandler: (handler) => { permission.request = handler; },
  };
  class FakeNotification {
    static isSupported() { return true; }
    constructor(options) { this.options = options; }
    show() { notification.show(); }
  }
  const camera = createCamera({
    BrowserWindow: FakeWindow,
    session: { fromPartition: () => captureSession },
    ipcMain,
    Notification: FakeNotification,
    audit,
    isAllowed: () => allowed,
    now,
    pagePath,
  });
  return { camera, audit, notification, calls, captureData, captureSession };
}

describe('camera snapshot guardrails', () => {
  test('disabled camera refuses without opening a window', async () => {
    const harness = cameraHarness({ allowed: false });
    await expect(harness.camera.snapshot()).resolves.toEqual({ ok: false, error: 'camera_disabled' });
    expect(harness.calls.loaded).toBe(0);
    expect(harness.audit.write).not.toHaveBeenCalled();
  });

  test('permits media only for the capture window local file page', async () => {
    const harness = cameraHarness();
    await expect(harness.camera.snapshot()).resolves.toEqual({
      image_b64: Buffer.from('jpeg').toString('base64'),
      mime: 'image/jpeg',
    });
    expect(harness.calls.permissionResults).toEqual([true, false, false]);
    expect(harness.notification.show).toHaveBeenCalledTimes(1);
    expect(harness.audit.write).toHaveBeenCalledWith(expect.objectContaining({ action: 'camera_snapshot' }));
    expect(JSON.stringify(harness.audit.write.mock.calls)).not.toContain(Buffer.from('jpeg').toString('base64'));
    expect(harness.calls.destroyed).toBe(1);
    expect(harness.captureSession.setPermissionRequestHandler).toBeDefined();
  });

  test('limits captures to one per five seconds', async () => {
    let instant = 10_000;
    const harness = cameraHarness({ now: () => instant });
    await harness.camera.snapshot();
    instant += 4_999;
    await expect(harness.camera.snapshot()).resolves.toEqual({ ok: false, error: 'camera_rate_limited' });
    instant += 1;
    await expect(harness.camera.snapshot()).resolves.toHaveProperty('mime', 'image/jpeg');
    expect(harness.calls.loaded).toBe(2);
  });
});

describe('window permissions and camera preference persistence', () => {
  test('pairing/status window permission requests and checks default to deny', () => {
    let requestHandler;
    let checkHandler;
    const window = {
      webContents: {
        session: {
          setPermissionRequestHandler: (handler) => { requestHandler = handler; },
          setPermissionCheckHandler: (handler) => { checkHandler = handler; },
        },
      },
    };
    denyWindowPermissions(window);
    for (const permission of ['media', 'notifications', 'clipboard-read']) {
      let granted;
      requestHandler({}, permission, (value) => { granted = value; });
      expect(granted).toBe(false);
    }
    expect(checkHandler({}, 'media', 'file:///untrusted.html')).toBe(false);
  });

  test('camera permission always resets OFF and is omitted from preferences', () => {
    expect(loadPreferences({ remoteEnabled: false, cameraAllowed: true, startWithWindows: true })).toEqual({
      remoteEnabled: false,
      cameraAllowed: false,
      startWithWindows: true,
    });
    expect(persistedPreferences({ remoteEnabled: true, cameraAllowed: true, startWithWindows: false })).toEqual({
      remoteEnabled: true,
      startWithWindows: false,
    });
  });
});