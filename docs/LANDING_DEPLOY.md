# Landing site and dashboard deployment

## 1. Create the Vercel project

1. Import the JARVIS repository in Vercel.
2. Set **Root Directory** to `landing/` and include it in the repository build.
3. Keep the framework preset as **Next.js**. Use `npm install`, `npm run build`, and `.next` as the build output.
4. Add the production and preview environment variables below, then redeploy.

The [landing/.env.example](../landing/.env.example) contains names only. Do not add real credentials to source control.

| Variable | Vercel value |
| --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key for the production Clerk instance |
| `CLERK_SECRET_KEY` | Clerk secret key; server-only, never prefix it with `NEXT_PUBLIC_` |
| `NEXT_PUBLIC_BACKEND_URL` | Public HTTPS origin for the JARVIS Flask backend, with no trailing slash |
| `NEXT_PUBLIC_DOWNLOAD_URL` | Direct URL to the latest installer asset on a GitHub Release |
| `NEXT_PUBLIC_DOWNLOAD_SHA256` | SHA-256 checksum for that exact installer asset |

Set the corresponding **Preview** values too, preferably using a separate Clerk development instance and a non-production backend. Never use a production backend URL in untrusted preview deployments.

## 2. Configure Clerk

In the Clerk Dashboard for the instance matching the publishable key:

- Add the production site origin (for example `https://jarvis.example.com`) to allowed origins.
- Add the exact sign-in URL `https://jarvis.example.com/sign-in`.
- Add the post-sign-in redirect `https://jarvis.example.com/app`.
- Configure the sign-in route as `/sign-in`; the dashboard uses `/app` after authentication.
- Copy the instance issuer URL and JWKS endpoint for the backend configuration in the next section.

For preview deployments, add the required preview origin and redirects, or use a separate Clerk development instance. Do not use a wildcard production origin unless Clerk explicitly requires and supports it.

## 3. Configure the backend

The dashboard sends a short-lived Clerk session token in `Authorization: Bearer ...` on every API request. The backend must be reachable over HTTPS and configured with:

- `CLERK_ISSUER`: the exact HTTPS issuer in Clerk session JWTs (no trailing slash).
- `CLERK_JWKS_URL`: the corresponding HTTPS `/.well-known/jwks.json` URL.
- `AUTH_MODE=clerk`: require Clerk bearer tokens; session cookies and password login are rejected.
- `ALLOWED_CLERK_SUBJECTS`: comma-separated allowlist of Clerk identities, written exactly as `clerk:<sub>`. Verified users outside the list receive HTTP 403 with `{"error":"not_allowed"}`. Development warns and permits all verified Clerk users when the list is empty; production refuses startup with an empty list unless `ALLOW_ANY_CLERK_USER=1` explicitly allows every verified Clerk user.
- `API_KEY_ENCRYPTION_KEY`: a persistent Fernet key used only by the backend to encrypt provider keys at rest. Generate a new value with:

  ```powershell
  py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  Store it in the backend hosting provider's secret manager. Back it up securely: losing it makes saved provider keys unreadable; rotating it requires re-encrypting stored keys before replacing it.

- `CORS_ORIGINS`: a comma-separated allowlist containing the exact Vercel production and approved preview origins; no `*`.
- `JARVIS_ENV=production`, plus `AUTH_MODE=clerk`, a strong `FLASK_SECRET`, `DATABASE_URL`, and `AUTH_ENABLED=1`. Production refuses local password/TOTP mode unless `ALLOW_LOCAL_AUTH=1` is explicitly set; that exception emits a critical security warning.

The backend's `backend-cloud/.env.example` has the backend-only variable names and setup notes. Do not place `API_KEY_ENCRYPTION_KEY`, Clerk secret keys, or AI provider keys in Vercel's `NEXT_PUBLIC_*` variables. The frontend never receives those values.

The backend API must be deployed before enabling the dashboard. Check `GET /api/health` for availability, then verify the new Clerk-authenticated `/api/keys` and `/api/devices` endpoints from the dashboard.

### Backend environment variables

Configure these in the backend hosting provider's secret manager, not in Vercel:

| Variable | Required | Purpose |
| --- | --- | --- |
| `AUTH_MODE` | `clerk` in production; defaults to `local` in development | Select `local` password + TOTP session auth or `clerk` bearer-token-only auth. |
| `ALLOW_LOCAL_AUTH` | No; default off | Explicitly permits local password/TOTP auth in production; logs a critical warning. |
| `CLERK_ISSUER` | Yes | HTTPS issuer expected in Clerk session JWTs. |
| `CLERK_JWKS_URL` | Yes | HTTPS JWKS endpoint; retrieval has a short timeout and cached signing keys. |
| `CLERK_AUTHORIZED_PARTIES` | Yes in production | Comma-separated exact allowed `azp` values. Keep this separate from the CORS allowlist. |
| `ALLOWED_CLERK_SUBJECTS` | Yes in production | Comma-separated `clerk:<sub>` user allowlist. Empty in development permits all verified Clerk users with a warning. |
| `ALLOW_ANY_CLERK_USER` | No; default off | Explicit production opt-out from the subject allowlist requirement; permits every verified Clerk user. |
| `API_KEY_ENCRYPTION_KEY` | Yes | Primary Fernet key used to encrypt provider keys at rest. |
| `API_KEY_ENCRYPTION_KEY_OLD` | Only during rotation | Previous Fernet key, accepted for decryption until the rotation completes. |
| `CORS_ORIGINS` | Yes in production | Comma-separated browser origins allowed by Flask CORS. Never use `*`. |
| `SERVER_FALLBACK_KEYS` | No; off by default | Set only to `1` to opt into server-wide provider-key fallback. Startup logs a prominent warning when enabled. |
| `JARVIS_ENV` | Production | Set to `production` to enforce production configuration and disable server-key use in ownerless background work. |
| `AUTH_ENABLED` | Yes in production | Must be enabled. |
| `FLASK_SECRET` | Yes in production | Strong random session-signing secret. |
| `DATABASE_URL` | Yes in production | Persistent PostgreSQL connection URL. |
| `DATABASE_URL_DIRECT` | Only for direct migration tools | Direct PostgreSQL endpoint for maintenance scripts; do not use a pooled endpoint. |
| `DB_BACKEND` | Optional | Select the database backend; production deployments should use PostgreSQL. |
| `TRUSTED_PROXY_HOPS` | Optional | Number of trusted reverse-proxy hops; configure only when the backend is behind a known proxy. |

For local development, include the local landing origin (normally `http://localhost:3000`) in both `CORS_ORIGINS` and `CLERK_AUTHORIZED_PARTIES`, and use a Clerk development instance. The Clerk `azp` must match an authorized-party entry; CORS origins do not implicitly authorize JWTs.

Provider keys belong to their authenticated user. Authenticated AI requests decrypt only that user's saved keys; ownerless background/system calls do not use server-wide keys in multi-user mode unless the explicit fallback is enabled.

To rotate encryption keys, configure the new primary key and the previous key as `API_KEY_ENCRYPTION_KEY_OLD`, run a dry run, then perform the rotation before removing the old key:

```powershell
Set-Location backend-cloud
py -m scripts.rotate_api_keys --dry-run
py -m scripts.rotate_api_keys
```

The script reports row counts only and never prints key material.

## 4. Custom domain and installer

Add the desired domain in Vercel, follow its DNS verification, and wait for the TLS certificate before updating Clerk allowed origins, `CORS_ORIGINS`, and the backend URL. Keep `NEXT_PUBLIC_BACKEND_URL` on HTTPS; the client refuses plain HTTP in production.

Publish the Windows installer as a GitHub Release asset. Set the download URL and SHA-256 from that same release. The current installer is unsigned and can trigger SmartScreen; the download page explains the warning and checksum verification.

## 5. Local checks

From `landing/`, run:

```powershell
npm install
npm run lint
npm test
npm run build
```

The UI smoke tests mock backend calls; use a separate staging backend and Clerk instance for a manual end-to-end verification before promoting a release.

### Troubleshooting

- A hydration warning mentioning `bis_skin_checked` is commonly caused by a browser extension injecting attributes into the page. Verify in a clean browser profile or disable the extension; do not change application markup to accommodate injected attributes.
- The production CSP intentionally uses exact Clerk Frontend API and Cloudflare challenge hosts and does not include Clerk's documented `*.protect.clerk.com` wildcard. This keeps the policy wildcard-free, but Clerk abuse/fraud protection hosts may be blocked; if that feature is required, revisit this tradeoff explicitly.
