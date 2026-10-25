'use strict';

function denyWindowPermissions(window) {
  const windowSession = window.webContents.session;
  windowSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  windowSession.setPermissionCheckHandler?.(() => false);
}

module.exports = { denyWindowPermissions };