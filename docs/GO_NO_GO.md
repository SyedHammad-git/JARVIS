# JARVIS v18 Go / No-Go

**Decision: NO-GO for production deployment.** Local code and test gates pass, but Neon migration counts and production release configuration are still unverified. No cloud writes or deployments were performed.

| Launch condition | Status | Evidence / remaining action |
| --- | --- | --- |
| Branch is `step20-final`; user-staged files are preserved | PASS | Commits used explicit paths. `.gitignore`, `backend-cloud/.env.example`, and `landing/.gitignore` remain pre-staged and uncommitted. |
| Phase 0 commit/tag exists | MANUAL | Commit `ec590ab`, tag `f1-p0-done`; no phase-specific acceptance transcript was found in the local session index. |
| Phase 1 commit/tag exists | MANUAL | Commit `67f95e6`, tag `f1-p1-done`; no phase-specific acceptance transcript was found. |
| Phase 2 commit/tag exists | MANUAL | Commit `a0c0cdc`, tag `f1-p2-done`; no phase-specific acceptance transcript was found. |
| Phase 3 source tests and download UI | PASS | Phase 3 commit `49d516f`; build-pipeline follow-up `0fd8488e598ad60da4503d1b782560f761e480e0`. Landing unit tests: `20 passed`; Playwright: `5 passed`. |
| Phase 3 production installer | MANUAL | The existing `client-electron/release/JARVIS-Device-Client-Setup-18.0.0.exe` was built before `BACKEND_URL` was embedded. Do not upload it. `npm run dist` now requires a valid `BACKEND_URL`; it was empty, so the guard stopped before electron-builder. Rebuild with the production HTTPS API origin, then verify/upload its checksum. |
| Phase 4 owner data isolation | PASS | Commit `40f9e596c8353c1080c0fda607fa290aef359794`, tag `f1-p4-done`; owner-scoped migrations, queries, caches, webhook purge, and isolation tests pass. |
| Phase 5 Neon migration dry-run counts | FAIL / BLOCKED | Preparation commit `2286dbcab467a64cdcd62c062605960e4fee6a8d` adds explicit dotenv loading and a safe probe. No counts were produced: the supplied `DATABASE_URL_DIRECT` host is a pooler and the migration refused before connecting with `ValueError`. A direct development endpoint is required. No real migration was run. |
| Phase 5 pooled connection / `channel_binding` | MANUAL | The safe probe reported `DATABASE_URL=EMPTY`; no pooled connection was attempted, so there is no connection result class and no channel-binding conclusion. |
| Phase 6 production hardening and files | PASS | Commit `59778b9d539ad57e72325ebab4b1634b71440bba`, tag `f1-p6-done`; final backend suite passes, deployment YAML parses, no `shell=True`/`sys.path` hacks found. |
| Phase 6 Docker/WSL container smoke | MANUAL | Docker is unavailable and WSL is not installed. Exact loopback-only Linux commands are in [docs/DEPLOY.md](docs/DEPLOY.md). |
| Phase 7 backend tests | PASS | Raw summary: `189 passed`. Includes idle DB, health, retry/fallback, pair-code, owner isolation, registry, prompt defense, and the headless pair-code → open_app → notify → mocked-snapshot flow through `/api/agent`. |
| Phase 7 landing checks | PASS | `npm run lint` passed; `npm test`: `20 passed`; `npm run build` passed with a local `metadataBase` fallback warning; `npm run test:e2e`: `5 passed`. |
| Phase 7 Electron suites | PASS | `npm test`: `13 passed`; `npm run test:camera`: `5 passed`. |
| Phase 7 diagnostics/whitespace | PASS | No backend editor diagnostics; staged and unstaged `git diff --check` passed. |
| Phase 7 secret scan | MANUAL | The source-only scan found none of the requested `sk_(live|test)_`, `whsec_`, or `npg_` token families. Gitleaks is unavailable here; run the documented Gitleaks command on a machine where it is installed. No `.env*` file was opened by the agent. |
| Production config values installed and verified | MANUAL | Production config checker correctly reports missing variable names in this development environment. Configure provider secret stores and run `python -m scripts.check_production_config` from `backend-cloud`. |
| Final release and real-device smoke | MANUAL | Publish the GitHub release, set all three landing download variables, rebuild the installer with `BACKEND_URL`, pair a PC over WSS, verify scopes/revocation and camera-off behavior, and run the live smoke guide. |

## Manual Steps Still Required

1. Rotate the Neon credential shared in chat. Set `DATABASE_URL` to the confirmed branch's pooled URL and `DATABASE_URL_DIRECT` to its **direct** development endpoint in your local secret store. Do not paste either value into chat.
2. From `backend-cloud`, run `python -m tools_dev.migrate_neon --dry-run` and review the per-table counts. No migration write may occur until you explicitly say `go real migration`.
3. Set a valid pooled `DATABASE_URL` locally and run `python -m scripts.check_neon_connection`. It reports only libpq version and `OK`, `auth`, `network`, or `channel_binding`. If it reports `channel_binding`, remove the `channel_binding` URL parameter and retry the probe.
4. Configure Clerk production, Neon, Vercel, and Render/VPS variables as listed in [docs/DEPLOY.md](docs/DEPLOY.md); restrict sign-ups and populate `ALLOWED_CLERK_SUBJECTS` with `clerk:<subject-id>` values.
5. Set the production `BACKEND_URL` in the Windows build environment, run `npm run dist` from `client-electron`, verify the `.exe.sha256`, upload both files to GitHub Releases, then set `NEXT_PUBLIC_DOWNLOAD_URL`, `NEXT_PUBLIC_DOWNLOAD_VERSION`, and `NEXT_PUBLIC_DOWNLOAD_SHA256` in the landing build environment.
6. Run the loopback smoke test on a Linux host with Docker/WSL or the documented local service commands; no public test ports are needed.
7. Run Gitleaks with the repository config, then complete the live WSS pairing, device notification, mocked/approved snapshot, revocation, and camera-off checks before deployment.
8. Confirm or supply the missing historical Phase 0–2 acceptance outputs if those phases must be certified under the commit + tag + acceptance-output rule. Their commits and tags exist; this session has no recorded acceptance results for them.
