'use strict';

const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { fileURLToPath, pathToFileURL } = require('node:url');

const CAPTURE_CHANNEL = 'camera:capture-result';
const MIN_CAPTURE_INTERVAL_MS = 5_000;

function isOwnCameraPage(requestingUrl, pagePath) {
  try {
    const parsed = new URL(requestingUrl);
    if (parsed.protocol !== 'file:') return false;
    parsed.search = '';
    parsed.hash = '';
    return path.resolve(fileURLToPath(parsed)) === path.resolve(pagePath);
  } catch {
    return false;
  }
}

function createCamera({
  BrowserWindow,
  session,
  ipcMain,
  Notification,
  audit,
  isAllowed,
  now = Date.now,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  pagePath = path.join(__dirname, 'ui', 'camera-capture.html'),
  preloadPath = path.join(__dirname, 'camera-preload.js'),
  captureTimeoutMs = 15_000,
} = {}) {
  let lastCaptureAt = -Infinity;
  let busy = false;

  async function snapshot({ width = 640, quality = 0.7 } = {}) {
    if (!isAllowed()) return { ok: false, error: 'camera_disabled' };
    if (busy) return { ok: false, error: 'camera_busy' };
    if (now() - lastCaptureAt < MIN_CAPTURE_INTERVAL_MS) {
      return { ok: false, error: 'camera_rate_limited' };
    }
    if (!Number.isInteger(width) || width < 160 || width > 1920
      || typeof quality !== 'number' || !Number.isFinite(quality) || quality < 0.1 || quality > 0.95) {
      return { ok: false, error: 'invalid_arguments' };
    }
    if (!Notification || !Notification.isSupported()) {
      return { ok: false, error: 'notifications_unavailable' };
    }

    lastCaptureAt = now();
    busy = true;
    const partition = `camera-capture-${randomUUID()}`;
    const captureSession = session.fromPartition(partition);
    let window;
    let timeout;
    let listener;

    try {
      window = new BrowserWindow({
        show: false,
        width: 1,
        height: 1,
        webPreferences: {
          partition,
          preload: preloadPath,
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: true,
          backgroundThrottling: false,
        },
      });

      const expectedPageUrl = pathToFileURL(pagePath).href;
      const permitted = (webContents, permission, requestingUrl) => (
        permission === 'media'
        && webContents === window.webContents
        && isOwnCameraPage(requestingUrl || webContents.getURL(), pagePath)
      );
      captureSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
        callback(permitted(webContents, permission, details?.requestingUrl));
      });
      const result = new Promise((resolve, reject) => {
        listener = (event, payload) => {
          if (event.sender !== window.webContents) return;
          resolve(payload);
        };
        ipcMain.on(CAPTURE_CHANNEL, listener);
        timeout = setTimer(() => reject(new Error('capture_timeout')), captureTimeoutMs);
      });

      await window.loadFile(pagePath, {
        query: { width: String(width), quality: String(quality) },
      });
      const payload = await result;
      if (!payload || payload.error) {
        return { ok: false, error: payload?.error || 'camera_capture_failed' };
      }
      const match = /^data:image\/jpeg;base64,([A-Za-z0-9+/]+={0,2})$/.exec(payload.dataUrl || '');
      if (!match) return { ok: false, error: 'camera_capture_failed' };

      const notification = new Notification({
        title: 'Camera snapshot captured',
        body: 'A camera snapshot was captured by J.A.R.V.I.S.',
      });
      notification.show();
      audit.write({
        action: 'camera_snapshot',
        args: { width, quality },
        result: { ok: true, mime: 'image/jpeg' },
      });
      return { image_b64: match[1], mime: 'image/jpeg' };
    } catch (error) {
      return { ok: false, error: error.message === 'capture_timeout' ? 'camera_timeout' : 'camera_unavailable' };
    } finally {
      clearTimer(timeout);
      if (listener) ipcMain.removeListener(CAPTURE_CHANNEL, listener);
      if (window && !window.isDestroyed()) window.destroy();
      captureSession.setPermissionRequestHandler(null);
      busy = false;
    }
  }

  return { snapshot };
}

module.exports = { CAPTURE_CHANNEL, MIN_CAPTURE_INTERVAL_MS, createCamera, isOwnCameraPage };