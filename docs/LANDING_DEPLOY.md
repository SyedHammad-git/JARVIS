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
- `API_KEY_ENCRYPTION_KEY`: a persistent Fernet key used only by the backend to encrypt provider keys at rest. Generate a new value with:

  ```powershell
  py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  Store it in the backend hosting provider's secret manager. Back it up securely: losing it makes saved provider keys unreadable; rotating it requires re-encrypting stored keys before replacing it.

- `CORS_ORIGINS`: a comma-separated allowlist containing the exact Vercel production and approved preview origins; no `*`.
- `JARVIS_ENV=production`, plus the existing production settings such as a strong `FLASK_SECRET`, `DATABASE_URL`, and `AUTH_ENABLED=1`.

The backend's `backend-cloud/.env.example` has the backend-only variable names and setup notes. Do not place `API_KEY_ENCRYPTION_KEY`, Clerk secret keys, or AI provider keys in Vercel's `NEXT_PUBLIC_*` variables. The frontend never receives those values.

The backend API must be deployed before enabling the dashboard. Check `GET /api/health` for availability, then verify the new Clerk-authenticated `/api/keys` and `/api/devices` endpoints from the dashboard.

For local development, include the local landing origin (normally `http://localhost:3000`) in `CORS_ORIGINS` and use a Clerk development instance. Clerk `azp` values must match one of the configured CORS origins.

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
