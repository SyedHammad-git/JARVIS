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
        if (stopped || !socket.connected) return;
        try {
          const statusUrl = new URL('/api/device/status', config.url);
          statusUrl.searchParams.set('device_id', config.deviceId);
          const response = await fetchImpl(statusUrl, { signal: AbortSignal.timeout(requestTimeoutMs) });
          if (response.ok) {
            const status = await response.json();
            if (status.execution_mode === 'remote' && status.online === false) {
              stop();
              onRevoked();
              return;
            }
          }
        } catch {
          // Network failure is not proof of revocation; Socket.IO manages reconnects.
        }
        if (!stopped && socket.connected) schedule();
      }, intervalMs);
    };

    schedule();
    return stop;
  }

  return { start, stop };
}

module.exports = { createRevocationMonitor };