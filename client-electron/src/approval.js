'use strict';

const { HIGH_RISK_ACTIONS } = require('./executor');

function createApproval({ dialog, timeoutMs = 30_000, setTimer = setTimeout, clearTimer = clearTimeout }) {
  async function request(action, details = {}) {
    if (!HIGH_RISK_ACTIONS.includes(action)) return false;
    let timer;
    const decision = Promise.resolve().then(() => dialog.showMessageBox({
      type: 'warning',
      title: 'J.A.R.V.I.S action approval',
      message: `Approve ${action}?`,
      detail: typeof details.summary === 'string' ? details.summary.slice(0, 300) : 'This action can affect your computer.',
      buttons: ['Approve', 'Deny'],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
    })).then((answer) => answer.response === 0);
    const timeout = new Promise((resolve) => {
      timer = setTimer(() => resolve(false), timeoutMs);
    });
    try {
      return await Promise.race([decision, timeout]);
    } catch {
      return false;
    } finally {
      clearTimer(timer);
    }
  }

  return { request };
}

module.exports = { createApproval };
