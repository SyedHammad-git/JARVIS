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

  function start(config, socket, onRevoked) {
    stop();
    stopped = false;

    const schedule = () => {
      clearTimer(timer);
      timer = setTimer(async () => {
        if (stopped) return;
        if (await check(config)) {
          stop();
          onRevoked();
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
      if (response.status === 401 || response.status === 403) return true;
      if (!response.ok) return false;
      const status = await response.json();
      return status.revoked === true || status.error === 'device_revoked';
    } catch {
      return false;
    }
  }

  return { check, start, stop };
}

function isRevokedConnectError(error) {
  return error?.message === 'device_revoked'
    || error?.data?.error === 'device_revoked'
    || error?.data === 'device_revoked';
}

module.exports = { createRevocationMonitor, isRevokedConnectError };