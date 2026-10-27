# Security Operations

## Secret handling

- Keep `.env` files local and out of Git, logs, screenshots, issue reports, and chat. Configuration diagnostics must report only variable names and set/empty or valid/invalid status.
- Store production values in the deployment provider's secret store. Do not add credentials to Render YAML, Compose files, Docker build args, source, tests, or docs.
- Runtime `DATABASE_URL` must be the Neon pooled URL with SSL enabled. `DATABASE_URL_DIRECT` is migration-only and must be a direct endpoint for the confirmed development branch; never provide the pooler URL there.
- Rotate the Neon database password in Neon, then update the pooled and direct URLs in their respective local/provider secret stores. Re-run the migration dry-run before considering a write.
- Provider API keys are per-user encrypted records. If one is exposed, delete and replace it in the account's Settings; do not copy it into backend environment variables.
- To rotate `API_KEY_ENCRYPTION_KEY`, pause writes to provider keys, retain the current key locally as `API_KEY_ENCRYPTION_KEY_OLD`, set a newly generated Fernet key as `API_KEY_ENCRYPTION_KEY`, run `python scripts/rotate_api_keys.py --dry-run`, then run `python scripts/rotate_api_keys.py`. The script reports a row count only. Keep the old key available until the real rotation succeeds and verify users can load their keys before removing it.
- Rotate `FLASK_SECRET` through the deployment secret store and restart the backend. Existing local sessions will need to sign in again.
- Revoke a leaked desktop device token from the account's Devices page; pair the PC again to issue a fresh token. Tokens are stored hashed and are shown only during pairing.
- Rotate `CLERK_WEBHOOK_SECRET` in Clerk and the backend secret store if the webhook signing secret is exposed.

## Production controls

- `AUTH_MODE=clerk` is mandatory in production. Set `ALLOWED_CLERK_SUBJECTS` to the intended Clerk subject IDs; only use `ALLOW_ANY_CLERK_USER=1` after an explicit access-control decision.
- `SERVER_FALLBACK_KEYS` must not be `1` in production. Keep `API_KEY_ENCRYPTION_KEY`, `FLASK_SECRET`, and `DATABASE_URL` in the platform's secret store.
- Set exact HTTPS origins in `CORS_ORIGINS`, `AUTHORIZED_PARTIES`, and `LANDING_URL`. No wildcards or URL paths are accepted for origin variables.
- Keep `TRUSTED_PROXY_HOPS=0` when the service is directly exposed. Behind exactly one trusted reverse proxy set it to `1`; never accept forwarded client addresses from untrusted hops.
- Bind local development to loopback. For production, put the service behind the configured TLS proxy. An always-on Render instance is required for persistent desktop WebSocket connections.
- Keep the camera off at desktop launch, retain per-device action scopes and revocation, require confirmation for risky actions, and do not put image/base64 data into logs, history, or audit records.

## Secret scanning

The repository Gitleaks config excludes `.env` files and defines additional patterns for `sk_(live|test)_`, `whsec_`, and `npg_` token families. Run from the repository root:

```powershell
gitleaks detect --no-git --source . --config .gitleaks.toml
```

If the scanner reports a value, do not paste it into a report. Record only the file path and rule ID, rotate the exposed credential, then remove the value from the tracked source and history through the repository's approved incident process.
