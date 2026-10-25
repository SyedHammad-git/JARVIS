'use strict';

function loadPreferences(saved = {}) {
  return {
    remoteEnabled: saved.remoteEnabled !== false,
    cameraAllowed: false,
    startWithWindows: saved.startWithWindows === true,
  };
}

function persistedPreferences(preferences) {
  return {
    remoteEnabled: preferences.remoteEnabled,
    startWithWindows: preferences.startWithWindows,
  };
}

module.exports = { loadPreferences, persistedPreferences };
