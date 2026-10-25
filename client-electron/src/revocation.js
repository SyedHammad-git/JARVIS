'use strict';

function createRevocationMonitor({
  fetchImpl = fetch,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  intervalMs = 15_000,
  requestTimeoutMs = 5_000,
} = {}) {
  let timer;
  let stopped = true;

  function stop() {
    stopped = true;
    clearTimer(timer);
  }

  function start(config, socket, onAuthorizationState) {
    stop();
    stopped = false;

    const schedule = () => {
      clearTimer(timer);
      timer = setTimer(async () => {
        if (stopped) return;
        const state = await check(config);
        if (state) {
          stop();
          onAuthorizationState(state);
          return;
        }
        if (!stopped) schedule();
      }, intervalMs);
    };

    schedule();
    return stop;
  }

  async function check(config) {
    try {
      const statusUrl = new URL('/api/device/status', config.url);
      statusUrl.searchParams.set('device_id', config.deviceId);
      const response = await fetchImpl(statusUrl, { signal: AbortSignal.timeout(requestTimeoutMs) });
      if (response.status === 401 || response.status === 403) return 'reauthentication';
      if (!response.ok) return null;
      const status = await response.json();
      return status.revoked === true ? 'revoked' : null;
    } catch {
      return null;
    }
  }

  return { check, start, stop };
}

function isRevokedConnectError(error) {
  return error?.data?.error === 'device_revoked'
    || error?.data === 'device_revoked';
}

function isUnauthorizedConnectError(error) {
  const status = error?.status ?? error?.data?.status ?? error?.context?.status;
  return status === 401 || status === 403;
}

module.exports = { createRevocationMonitor, isRevokedConnectError, isUnauthorizedConnectError };