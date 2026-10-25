'use strict';

const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('jarvis', Object.freeze({
  getPairing: () => ipcRenderer.invoke('pairing:get'),
  saveAndConnect: (config) => ipcRenderer.invoke('pairing:save-connect', config),
  openPairing: () => ipcRenderer.invoke('pairing:open'),
  connect: () => ipcRenderer.invoke('device:connect'),
  getStatus: () => ipcRenderer.invoke('device:status'),
  onStatus: (callback) => subscribe('device:status-update', callback),
  onLastCommand: (callback) => subscribe('device:last-command', callback),
}));