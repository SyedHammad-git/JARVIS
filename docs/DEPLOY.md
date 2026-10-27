# JARVIS v18 Deployment Guide

No deployment, sign-in, or cloud-resource changes are performed by this repository workflow. Follow these steps in your own provider accounts.

## 1. Prepare Neon

1. In Neon, create a **production** branch from the intended production baseline and a separate **development** branch for migration/testing. Do not share a database branch between staging and production.
2. In each branch's connection dialog, select the pooled connection for the running backend. Enable SSL; use the pooled hostname for `DATABASE_URL`.
3. For schema work only, copy the direct endpoint for the confirmed development branch into a local `DATABASE_URL_DIRECT` environment variable. Do not use a `-pooler` hostname for this variable.
4. From `backend-cloud`, run `python -m tools_dev.migrate_neon --dry-run`. Review every table count and the branch label. Do not run without `--dry-run` until the branch is confirmed and the operator explicitly approves the migration.
5. Keep the production branch URL separate from the development branch URL. Do not paste either connection string into chat, Git, screenshots, logs, or command-line arguments.

## 2. Configure Clerk Production

1. Create/select the production Clerk instance and add the final landing domain.
2. Add the landing URL to Clerk's allowed origins and redirect URLs. Configure the production sign-in/sign-up redirect to `/app`.
3. In Clerk's sign-up settings, restrict registration to the intended users (for example, invite-only or disabled public sign-up).
4. Create an endpoint for `https://<api-domain>/api/webhooks/clerk` and subscribe to `user.deleted`.
5. Put the webhook signing secret only in the backend secret store. The endpoint validates Svix signatures and is intentionally outside the normal auth guard.
6. Record variable names for later configuration: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_ISSUER`, `CLERK_JWKS_URL`, `AUTHORIZED_PARTIES`, `ALLOWED_CLERK_SUBJECTS`, and `CLERK_WEBHOOK_SECRET`.

## 3. Deploy the Landing on Vercel

1. In Vercel, import the repository and set the project root directory to `landing`.
2. Configure the production domain, then configure the same domain in Clerk and the backend CORS allowlist.
3. Add these environment variables to Vercel's Production environment, then deploy:
   - `NEXT_PUBLIC_SITE_URL`: landing HTTPS origin.
   - `NEXT_PUBLIC_BACKEND_URL`: backend HTTPS origin, with no path.
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`: Clerk production publishable key.
   - `CLERK_SECRET_KEY`: Clerk production secret key; keep it in Vercel's secret environment, never in the browser bundle.
   - `NEXT_PUBLIC_DOWNLOAD_URL`: HTTPS GitHub Release installer asset URL, or leave empty until published.
   - `NEXT_PUBLIC_DOWNLOAD_VERSION`: installer version, or leave empty until published.
   - `NEXT_PUBLIC_DOWNLOAD_SHA256`: 64-character installer digest, or leave empty until published.
4. Confirm the landing site's API origin exactly matches `NEXT_PUBLIC_BACKEND_URL` and its domain exactly matches the backend's `CORS_ORIGINS` and Clerk `AUTHORIZED_PARTIES` entries.

## 4. Deploy the Backend on Render

1. In Render, create a Blueprint from the repository and review the root `render.yaml`. It defines one web service only; Neon is the database.
2. Set the API subdomain and health check `/api/ping`.
3. Add these values in Render's environment UI. Secret entries are marked `sync: false` in the Blueprint; never commit their values:
   - `DATABASE_URL`: Neon production **pooled** URL with `sslmode=require`.
   - `API_KEY_ENCRYPTION_KEY`: valid Fernet key.
   - `FLASK_SECRET`: high-entropy secret, 32+ characters.
   - `CLERK_ISSUER`: production Clerk issuer HTTPS URL.
   - `CLERK_JWKS_URL`: production Clerk JWKS HTTPS URL.
   - `AUTHORIZED_PARTIES`: exact landing HTTPS origin(s), comma-separated.
   - `ALLOWED_CLERK_SUBJECTS`: allowed subjects in the exact runtime form `clerk:<subject-id>`, comma-separated.
   - `CLERK_WEBHOOK_SECRET`: Svix signing secret.
   - `CORS_ORIGINS`: exact landing HTTPS origin(s), comma-separated.
   - `LANDING_URL`: landing HTTPS origin.
   - `ALLOW_ANY_CLERK_USER`: leave unset unless you have explicitly decided to permit all verified Clerk accounts.
4. Keep Blueprint values `JARVIS_ENV=production`, `DB_BACKEND=postgres`, `AUTH_MODE=clerk`, `AUTH_ENABLED=1`, `SERVER_FALLBACK_KEYS=0`, and set `TRUSTED_PROXY_HOPS` to the actual trusted Render proxy count.
5. Before starting a local production-like process, run `python -m scripts.check_production_config` from `backend-cloud`. It prints only PASS/FAIL and invalid variable names. Render also refuses startup if the production environment is invalid.
6. Use a paid, always-on Render instance for the device gateway. A sleeping free instance drops persistent device WebSockets; it is not suitable for connected desktop devices.
7. Map separate domains such as `app.example.com` (Vercel) and `api.example.com` (Render), then update Vercel's `NEXT_PUBLIC_BACKEND_URL`, Clerk origins, backend `CORS_ORIGINS`, `AUTHORIZED_PARTIES`, and `LANDING_URL` to those exact domains.

## 5. Alternative: One-Domain VPS

1. Provision a Linux host and DNS record for one domain. Permit inbound TCP 80/443 to Caddy only; do not expose the backend or landing container ports.
2. Install Docker Engine and the Compose plugin, clone the release commit, and create a local `deploy/vps/.env` from the variable names listed below. Keep it out of Git.
3. Set `JARVIS_DOMAIN`, `DATABASE_URL`, `API_KEY_ENCRYPTION_KEY`, `FLASK_SECRET`, `CLERK_ISSUER`, `CLERK_JWKS_URL`, `AUTHORIZED_PARTIES`, `ALLOWED_CLERK_SUBJECTS`, `CLERK_WEBHOOK_SECRET`, `CORS_ORIGINS`, `LANDING_URL`, `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `NEXT_PUBLIC_SITE_URL`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_DOWNLOAD_URL`, `NEXT_PUBLIC_DOWNLOAD_VERSION`, and `NEXT_PUBLIC_DOWNLOAD_SHA256` as applicable.
4. For this layout, use `LANDING_URL=https://<domain>`, `NEXT_PUBLIC_BACKEND_URL=https://<domain>`, and `CORS_ORIGINS=https://<domain>`. Keep `TRUSTED_PROXY_HOPS=1`; Compose does not publish backend/landing ports, and Caddy proxies `/api/*`, `/pairing/*`, and `/socket.io/*` with WebSocket upgrades to the backend and all other paths to the landing.
5. Build/start with `docker compose -f deploy/vps/docker-compose.yml up -d --build`. Caddy obtains and renews TLS certificates automatically.
6. For a systemd deployment instead of the backend container, install the Python requirements in a virtual environment, create the `jarvis` service user, create `/var/lib/jarvis` owned by `jarvis`, and create `/etc/jarvis/backend.env` owned by `root:jarvis` with mode `0640`. Install `deploy/vps/jarvis-backend.service` and put that Gunicorn service behind Caddy. Set the production variable names from the Render section and `TRUSTED_PROXY_HOPS=1`.

## 6. First Login and Pair a PC

1. Open the landing domain and sign in through the production Clerk instance.
2. Confirm the new user's Clerk subject is present in `ALLOWED_CLERK_SUBJECTS`. With an allowlist configured, other subjects receive `403`.
3. On the signed-in dashboard, open Devices and create an 8-character pairing code.
4. On the Windows PC, install the per-user NSIS installer from the verified release. Set `BACKEND_URL` to the backend HTTPS origin during the release build so the production pairing URL is locked; the client uses WebSocket transport (`wss://`) and rejects production HTTP.
5. Open the desktop app and enter the one-time pairing code before it expires. Verify the device appears online, then review and grant only the needed per-device scopes. Camera remains off at launch.

## 7. Smoke Test and Rollback

1. Check public health: `curl -fsS https://<api-domain>/api/ping`.
2. Confirm protected API behavior without a token: `curl -sS -o /dev/null -w "%{http_code}\n" -X POST https://<api-domain>/api/agent -H "Content-Type: application/json" -d "{}"` should print `401`.
3. Create a test device pairing code in the dashboard. Store its device ID and token in local shell variables without echoing the token; the token is returned once.
4. From a secured Linux shell, run `JARVIS_TEST_DEVICE_TOKEN="$DEVICE_TOKEN" python tools_dev/fake_device.py --url https://<api-domain> --device-id "$DEVICE_ID" --token-env JARVIS_TEST_DEVICE_TOKEN`. The client forces WebSocket transport; TLS makes this a WSS connection. Confirm `connected namespace=/device`, issue a benign notification/snapshot action, then revoke the fake device.
5. For rollback, check out the existing `pre-split` tag and redeploy the previous artifacts from their provider histories. No database rollback is automatic; take a provider snapshot and use the database operator runbook before reversing schema changes.

### Linux Smoke Test When No Local Container Engine Is Available

Run this only on a Linux host you control. This self-contained command binds the temporary smoke backend to loopback, uses process-local generated configuration, and does not point at Neon or any public address:

```sh
cd backend-cloud
export JARVIS_ENV=production AUTH_MODE=clerk AUTH_ENABLED=1 DB_BACKEND=postgres
export SERVER_FALLBACK_KEYS=0 TRUSTED_PROXY_HOPS=0 JARVIS_SMOKE_TEST=1 JARVIS_SKIP_DOTENV=1
export FLASK_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export API_KEY_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export DATABASE_URL="$(python -c 'from urllib.parse import urlunsplit; print(urlunsplit(("postgresql", "localhost:5432", "/jarvis", "sslmode=require", "")))')"
export CLERK_ISSUER='https://clerk.invalid' CLERK_JWKS_URL='https://clerk.invalid/jwks'
export AUTHORIZED_PARTIES='https://localhost' ALLOWED_CLERK_SUBJECTS='clerk:smoke-test'
export CORS_ORIGINS='https://localhost' LANDING_URL='https://localhost'
export JARVIS_DATA_DIR="$(mktemp -d)"
gunicorn --config gunicorn.conf.py --bind 127.0.0.1:18080 wsgi:app >"$JARVIS_DATA_DIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; rm -rf "$JARVIS_DATA_DIR"' EXIT
for attempt in $(seq 1 30); do
   if curl -fsS http://127.0.0.1:18080/api/ping >/dev/null; then break; fi
   sleep 1
done
PING_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/api/ping)
AGENT_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:18080/api/agent -H 'Content-Type: application/json' -d '{}')
HEALTH=$(curl -fsS http://127.0.0.1:18080/api/health)
printf 'PING_HTTP=%s AGENT_HTTP=%s\n' "$PING_STATUS" "$AGENT_STATUS"
printf '%s\n' "$HEALTH" | grep -Eo '"(db_backend|sqlite_fallback_active)"[[:space:]]*:[[:space:]]*("[^"]*"|true|false)'
test "$PING_STATUS" = 200 && test "$AGENT_STATUS" = 401
python -m tools_dev.smoke_websocket --url http://127.0.0.1:18080
```

Expected output includes `PING_HTTP=200`, `AGENT_HTTP=401`, `db_backend="sqlite"`, `sqlite_fallback_active=true`, and `WEBSOCKET=PASS`. The local PostgreSQL connection intentionally fails and exercises bounded cold-start retry and SQLite fallback. The helper creates and revokes a temporary local device and never prints its token. The trap stops only the Gunicorn process started by this command and removes only its `mktemp` directory.
