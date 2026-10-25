'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cameraCapture', Object.freeze({
  submit: (dataUrl) => ipcRenderer.send('camera:capture-result', { dataUrl }),
  fail: () => ipcRenderer.send('camera:capture-result', { error: 'camera_unavailable' }),
}));