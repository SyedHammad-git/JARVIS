# JARVIS Desktop Release

## Build on Windows

1. Check out the release commit and confirm `client-electron/package.json` has the intended version. electron-builder reads this version directly.
2. In PowerShell, install dependencies if needed and build from the Electron package directory:
   ```powershell
   Push-Location client-electron
   npm ci
   npm run dist
   Pop-Location
   ```
3. Set `BACKEND_URL` to the production backend's HTTPS origin in the build environment. `scripts/build.ps1` validates and embeds the origin in a temporary ignored config file, then removes only the file it created; the packaged client locks its pairing form to this URL and production does not accept HTTP.
4. Confirm the installer and matching checksum file exist under `client-electron/release/`:
   - `JARVIS-Device-Client-Setup-<version>.exe`
   - `JARVIS-Device-Client-Setup-<version>.exe.sha256`
6. Verify the checksum against the installer with `Get-FileHash -Algorithm SHA256` before upload.

The NSIS installer is per-user and is not code-signed. Windows SmartScreen may therefore show a warning. A checksum confirms file integrity, not publisher identity.

## Publish a GitHub Release

1. In GitHub, open the repository's Releases page and choose **Draft a new release**.
2. Create a tag named `v<version>` from the intended release commit.
3. Use the same version as the release title and publish notes that describe only verified changes.
4. Upload both the `.exe` installer and its `.exe.sha256` file from `client-electron/release/`.
5. Publish the release, then copy the installer's HTTPS GitHub Release asset URL and the SHA-256 digest from the checksum file.

## Configure the Landing Download

Set these public build-time environment variables for the landing deployment, then rebuild/redeploy the landing:

- `NEXT_PUBLIC_DOWNLOAD_URL`: HTTPS GitHub Release asset URL for the `.exe` file.
- `NEXT_PUBLIC_DOWNLOAD_VERSION`: exact version from `client-electron/package.json`, without a `v` prefix.
- `NEXT_PUBLIC_DOWNLOAD_SHA256`: 64-character hexadecimal SHA-256 digest for that exact installer.

When `NEXT_PUBLIC_DOWNLOAD_URL` is unset, the landing displays a disabled **Coming soon** button rather than a dead or unrelated link.