'use strict';

const fs = require('node:fs');
const path = require('node:path');

const FILE_HEADER = Buffer.from('JARVISCFG1\n', 'ascii');

function validateConfig(config, devMode = process.env.JARVIS_DEV === '1') {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('invalid_config');
  }
  if (typeof config.url !== 'string' || typeof config.deviceId !== 'string' || typeof config.token !== 'string') {
    throw new Error('invalid_config');
  }
  const url = new URL(config.url.trim());
  const localHost = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  const allowed = url.protocol === 'https:' || (devMode && localHost && url.protocol === 'http:');
  if (!allowed || url.username || url.password || url.search || url.hash) {
    throw new Error('insecure_url');
  }
  const deviceId = config.deviceId.trim();
  const token = config.token.trim();
  if (!deviceId || deviceId.length > 200 || /[\u0000-\u001f]/.test(deviceId) || !token || token.length > 2048) {
    throw new Error('invalid_config');
  }
  return { url: url.toString().replace(/\/$/, ''), deviceId, token };
}

function createStore({ app, safeStorage, fsModule = fs }) {
  const filePath = path.join(app.getPath('userData'), 'device-credentials.dat');

  function save(config) {
    const validated = validateConfig(config);
    if (!safeStorage.isEncryptionAvailable()) throw new Error('encryption_unavailable');
    const encrypted = safeStorage.encryptString(JSON.stringify(validated));
    const temporaryPath = `${filePath}.tmp`;
    fsModule.writeFileSync(temporaryPath, Buffer.concat([FILE_HEADER, encrypted]));
    try {
      fsModule.renameSync(temporaryPath, filePath);
    } catch (error) {
      if (!fsModule.existsSync(filePath)) throw error;
      fsModule.unlinkSync(filePath);
      fsModule.renameSync(temporaryPath, filePath);
    }
    return { url: validated.url, deviceId: validated.deviceId };
  }

  function load() {
    if (!fsModule.existsSync(filePath)) return null;
    if (!safeStorage.isEncryptionAvailable()) throw new Error('encryption_unavailable');
    const data = fsModule.readFileSync(filePath);
    if (data.length <= FILE_HEADER.length || !data.subarray(0, FILE_HEADER.length).equals(FILE_HEADER)) {
      throw new Error('invalid_encrypted_store');
    }
    const decoded = JSON.parse(safeStorage.decryptString(data.subarray(FILE_HEADER.length)));
    return validateConfig(decoded);
  }

  function clear() {
    if (fsModule.existsSync(filePath)) fsModule.unlinkSync(filePath);
  }

  return { save, load, clear, filePath };
}

module.exports = { createStore, validateConfig };
