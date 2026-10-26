'use strict';

const fs = require('node:fs');
const path = require('node:path');

const MAX_BYTES = 2 * 1024 * 1024;

function safeText(value) {
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, '');
  if (/data:[^\s,]*;base64,[A-Za-z0-9+/=_-]+/i.test(cleaned)
    || /(?:^|[^A-Za-z0-9+/=])[A-Za-z0-9+/]{128,}={0,2}(?=$|[^A-Za-z0-9+/=])/.test(cleaned)) {
    return '[omitted]';
  }
  return cleaned.slice(0, 160);
}

function safeValue(value, depth = 0) {
  if (depth > 2) return '[omitted]';
  if (typeof value === 'string') return safeText(value);
  if (typeof value === 'number' || typeof value === 'boolean' || value === null) return value;
  if (Array.isArray(value)) return value.slice(0, 10).map((item) => safeValue(item, depth + 1));
  if (value && typeof value === 'object') {
    const result = {};
    for (const [key, item] of Object.entries(value).slice(0, 20)) {
      if (/token|secret|password|credential|authorization|image|base64|data.?url|snapshot/i.test(key)) continue;
      result[safeValue(key)] = safeValue(item, depth + 1);
    }
    return result;
  }
  return '[omitted]';
}

function createAudit({ app, fsModule = fs }) {
  const filePath = path.join(app.getPath('userData'), 'audit.jsonl');
  const backupPath = `${filePath}.1`;

  function write(entry) {
    try {
      const line = `${JSON.stringify({ time: new Date().toISOString(), ...safeValue(entry) })}\n`;
      if (fsModule.existsSync(filePath) && fsModule.statSync(filePath).size + Buffer.byteLength(line) > MAX_BYTES) {
        if (fsModule.existsSync(backupPath)) fsModule.unlinkSync(backupPath);
        fsModule.renameSync(filePath, backupPath);
      }
      fsModule.appendFileSync(filePath, line, { encoding: 'utf8' });
      return true;
    } catch {
      return false;
    }
  }

  return { write, filePath };
}

module.exports = { createAudit, safeValue, MAX_BYTES };
