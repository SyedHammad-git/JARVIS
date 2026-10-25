'use strict';

const { app, BrowserWindow, dialog, ipcMain, Menu, Notification, safeStorage, session, shell, Tray } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { io } = require('socket.io-client');
const { createApproval } = require('./approval');
const { createAudit } = require('./audit');
const { createCamera } = require('./camera');
const { createCommandHandler, createExecutor, HIGH_RISK_ACTIONS } = require('./executor');
const { createRevocationMonitor, isRevokedConnectError, isUnauthorizedConnectError } = require('./revocation');
const { loadPreferences, persistedPreferences } = require('./preferences');
const { redeemPairCode } = require('./pairing');
const { createStore, validateConfig } = require('./store');
const { denyWindowPermissions } = require('./window-security');

if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

const store = createStore({ app, safeStorage });
const audit = createAudit({ app });
const approval = createApproval({ dialog });
const preferencesPath = path.join(app.getPath('userData'), 'preferences.json');
let preferences = loadPreferences();
let tray;
let pairingWindow;
let statusWindow;
let socket;
let commandHandler;
let lastCommand = 'None';
let connectionState = 'Not connected';
let quitting = false;
let revoked = false;
let reauthenticationNeeded = false;
const revocationMonitor = createRevocationMonitor();

try {
  const savedPreferences = JSON.parse(fs.readFileSync(preferencesPath, 'utf8'));
  preferences = loadPreferences(savedPreferences);
} catch {
  // First run starts with remote control enabled and camera access disabled.
}

const camera = createCamera({
  BrowserWindow,
  session,
  ipcMain,
  Notification,
  audit,
  isAllowed: () => preferences.cameraAllowed,
});
const executor = createExecutor({ shell, Notification, cameraSnapshot: (options) => camera.snapshot(options) });

function savePreferences() {
  fs.writeFileSync(preferencesPath, JSON.stringify(persistedPreferences(preferences)), { encoding: 'utf8', mode: 0o600 });
}

function setStatus(value) {
  connectionState = value;
  statusWindow?.webContents.send('device:status-update', value);
  rebuildTrayMenu();
}

function setLastCommand(value) {
  lastCommand = value;
  statusWindow?.webContents.send('device:last-command', value);
}

function protectWindow(window) {
  denyWindowPermissions(window);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.webContents.on('will-attach-webview', (event) => event.preventDefault());
  window.on('close', (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
}

function windowOptions(options) {
  return {
    ...options,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  };
}

function openPairingWindow() {
  if (pairingWindow && !pairingWindow.isDestroyed()) {
    pairingWindow.show();
    pairingWindow.focus();
    return;
  }
  pairingWindow = new BrowserWindow(windowOptions({ width: 520, height: 510, resizable: false, title: 'J.A.R.V.I.S Pairing' }));
  protectWindow(pairingWindow);
  pairingWindow.on('closed', () => { pairingWindow = null; });
  pairingWindow.loadFile(path.join(__dirname, 'ui', 'pairing.html'));
}

function openStatusWindow() {
  if (statusWindow && !statusWindow.isDestroyed()) {
    statusWindow.show();
    statusWindow.focus();
    return;
  }
  statusWindow = new BrowserWindow(windowOptions({ width: 520, height: 360, resizable: false, title: 'J.A.R.V.I.S Device Status' }));
  protectWindow(statusWindow);
  statusWindow.on('closed', () => { statusWindow = null; });
  statusWindow.loadFile(path.join(__dirname, 'ui', 'status.html'));
}

function rebuildTrayMenu() {
  if (!tray) return;
  const menu = Menu.buildFromTemplate([
    { label: `Status: ${connectionState}`, enabled: false },
    { type: 'separator' },
    { label: 'Open status', click: openStatusWindow },
    { label: 'Pair device', click: openPairingWindow },
    { label: 'Remote control', type: 'checkbox', checked: preferences.remoteEnabled, click: (item) => {
      preferences.remoteEnabled = item.checked;
      savePreferences();
    } },
    { label: 'Camera allowed', type: 'checkbox', checked: preferences.cameraAllowed, click: (item) => {
      preferences.cameraAllowed = item.checked;
      savePreferences();
    } },
    { label: 'Open audit log', click: () => shell.openPath(audit.filePath) },
    { label: 'Start with Windows', type: 'checkbox', checked: preferences.startWithWindows, click: (item) => {
      preferences.startWithWindows = item.checked;
      app.setLoginItemSettings({ openAtLogin: item.checked });
      savePreferences();
    } },
    { type: 'separator' },
    { label: 'Quit', click: () => { quitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(menu);
  tray.setToolTip(`J.A.R.V.I.S: ${connectionState}`);
}

async function connectDevice() {
  if (revoked) throw new Error('device_revoked');
  reauthenticationNeeded = false;
  const config = store.load();
  if (!config) throw new Error('pairing_required');
  validateConfig(config);
  revocationMonitor.stop();
  socket?.disconnect();
  setStatus('Connecting');
  commandHandler = createCommandHandler({
    execute: async (action, args) => {
      if (HIGH_RISK_ACTIONS.includes(action) && !await approval.request(action, { summary: 'Requested remotely' })) {
        return { ok: false, error: 'needs_confirmation' };
      }
      return executor.execute(action, args);
    },
    isRemoteEnabled: () => preferences.remoteEnabled,
    audit,
  });
  socket = io(`${config.url}/device`, {
    auth: { device_id: config.deviceId, token: config.token },
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 30_000,
    randomizationFactor: 0,
  });
  socket.on('connect', () => {
    revoked = false;
    setStatus('Connected');
    revocationMonitor.start(config, socket, (state) => {
      socket.disconnect();
      if (state === 'revoked') {
        revoked = true;
        store.clear();
        setStatus('Device revoked; reconnect disabled');
      } else {
        reauthenticationNeeded = true;
        setStatus('Re-authentication needed');
      }
    });
  });
  socket.on('connect_error', (error) => {
    if (isRevokedConnectError(error)) {
      revoked = true;
      revocationMonitor.stop();
      store.clear();
      socket.disconnect();
      setStatus('Device revoked; reconnect disabled');
      return;
    }
    if (isUnauthorizedConnectError(error)) {
      reauthenticationNeeded = true;
      revocationMonitor.stop();
      socket.disconnect();
      setStatus('Re-authentication needed');
      return;
    }
    setStatus('Connection rejected or unavailable; retrying');
  });
  socket.on('disconnect', (reason) => {
    if (revoked || reauthenticationNeeded) return;
    if (reason === 'io server disconnect') {
      setStatus('Disconnected by server; checking authorization');
      revocationMonitor.check(config).then((state) => {
        if (state === 'revoked') {
          revoked = true;
          revocationMonitor.stop();
          store.clear();
          setStatus('Device revoked; reconnect disabled');
        } else if (state === 'reauthentication') {
          reauthenticationNeeded = true;
          revocationMonitor.stop();
          setStatus('Re-authentication needed');
        } else if (!revoked) {
          setStatus('Disconnected; retrying');
          socket.connect();
        }
      });
      return;
    }
    setStatus('Disconnected; retrying');
  });
  socket.on('command', async (command, acknowledge) => {
    const result = await commandHandler.handle(command);
    const action = typeof command?.action === 'string' ? command.action.slice(0, 64) : 'unknown';
    setLastCommand(`${action}: ${result.ok ? 'ok' : result.error}`);
    if (typeof acknowledge === 'function') acknowledge(result);
  });
  return true;
}

ipcMain.handle('pairing:get', () => {
  try {
    const config = store.load();
    return config ? { url: config.url, deviceId: config.deviceId, hasToken: true } : { url: '', deviceId: '', hasToken: false };
  } catch {
    return { url: '', deviceId: '', error: 'Stored pairing is unavailable; pair again.' };
  }
});
ipcMain.handle('pairing:redeem-connect', async (_event, details) => {
  const config = await redeemPairCode(details);
  const saved = store.save(config);
  revoked = false;
  await connectDevice();
  return saved;
});
ipcMain.handle('device:connect', () => connectDevice());
ipcMain.handle('device:status', () => ({ state: connectionState, lastCommand }));
ipcMain.handle('pairing:open', () => openPairingWindow());

app.on('second-instance', () => {
  openStatusWindow();
});

app.whenReady().then(async () => {
  const iconPath = path.join(__dirname, 'ui', 'icon.png');
  tray = new Tray(iconPath);
  tray.on('double-click', openStatusWindow);
  rebuildTrayMenu();
  app.setLoginItemSettings({ openAtLogin: preferences.startWithWindows });
  openStatusWindow();
  try {
    if (store.load()) await connectDevice();
    else openPairingWindow();
  } catch {
    setStatus('Pairing required');
    openPairingWindow();
  }
});

app.on('activate', openStatusWindow);
app.on('window-all-closed', () => {});
