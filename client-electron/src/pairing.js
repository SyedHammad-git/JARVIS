'use strict';

function validateBackendUrl(value, devMode = process.env.JARVIS_DEV === '1') {
  let url;
  try {
    url = new URL(typeof value === 'string' ? value.trim() : '');
  } catch {
    throw new Error('invalid_backend_url');
  }
  const localHost = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  const allowed = url.protocol === 'https:' || (devMode && localHost && url.protocol === 'http:');
  if (!allowed || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('insecure_url');
  }
  return url.toString().replace(/\/$/, '');
}

function configuredBackendUrl(value = process.env.BACKEND_URL, devMode = process.env.JARVIS_DEV === '1') {
  if (typeof value !== 'string' || !value.trim()) return '';
  return validateBackendUrl(value, devMode);
}

async function redeemPairCode({ url, code, name = 'PC' }, fetchImpl = fetch, devMode = process.env.JARVIS_DEV === '1') {
  const backendUrl = validateBackendUrl(url, devMode);
  const normalizedCode = typeof code === 'string' ? code.trim().toUpperCase() : '';
  if (!/^[A-HJ-NP-Z2-9]{8}$/.test(normalizedCode)) throw new Error('invalid_pair_code');

  let response;
  try {
    response = await fetchImpl(`${backendUrl}/pairing/redeem-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: normalizedCode, name }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    throw new Error('backend_unavailable');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error === 'pair_code_expired_or_invalid' ? 'pair_code_expired_or_invalid' : 'pairing_failed');
  }
  const payload = await response.json();
  if (!payload || typeof payload.device_id !== 'string' || typeof payload.token !== 'string') {
    throw new Error('invalid_pairing_response');
  }
  return { url: backendUrl, deviceId: payload.device_id, token: payload.token };
}

module.exports = { configuredBackendUrl, redeemPairCode, validateBackendUrl };
