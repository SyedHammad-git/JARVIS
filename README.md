# J.A.R.V.I.S v18.0.0 — Modular Edition

**Just A Rather Very Intelligent System**  
Built by Hammad • Iron Man Edition

---

## Quick Start

```powershell
# Run these commands from backend-cloud/ in PowerShell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt

# If backend-cloud/.env does not exist, create it from the example and add your own values.
Copy-Item .env.example .env

$env:DB_BACKEND = "sqlite"
py wsgi.py

# Run backend tests
py -m pytest -q
```

The app loads `backend-cloud/.env` by an absolute package-derived path, regardless of the
current working directory. Public binds are refused unless `ALLOW_PUBLIC_BIND=1` is set.
Development defaults to `AUTH_MODE=local` for password + TOTP session login. Production
requires `AUTH_MODE=clerk`; `ALLOW_LOCAL_AUTH=1` is an explicit, loudly logged exception.
The cloud backend does not execute local OS actions. Those actions are dispatched only
to a paired Electron client.

Open: http://localhost:5000  
Mobile: http://localhost:5000/mobile  
Health: http://localhost:5000/api/health

From the repository root, `.\dev-all.ps1` starts the Flask backend with SQLite and
the Next.js landing site in separate PowerShell windows. It waits for backend
`/api/ping` and the landing site to respond before opening http://localhost:3000.
Configure the local environment files first; the launcher does not print or
inspect their contents.

---

## Architecture

```
JARVIS_v17M/
├── backend-cloud/
│   ├── wsgi.py             - Flask-SocketIO development entry point
│   ├── app/                - Application factory and runtime packages
│   │   ├── ai/             - Agent and provider engine
│   │   ├── db/             - SQLite/PostgreSQL abstraction
│   │   ├── devices/        - Paired-device gateway
│   │   ├── routes/         - Flask API and UI routes
│   │   ├── static/         - Desktop and mobile HTML
│   │   ├── tools/          - Tool registry and implementations
│   │   ├── vector/         - Neon pgvector store
│   │   └── vision/         - Snapshot handling
│   ├── tests/              - Backend tests
│   ├── scripts/            - Backfill and real-start smoke test
│   └── tools_dev/          - Development utilities
└── client-electron/        - Local device client
```

---

## Database Switch

```env
# Local dev (default — zero config):
DB_BACKEND=sqlite

# Neon production (pooled app URL; direct URL only for migrations):
DB_BACKEND=postgres
DATABASE_URL=postgresql://user:password@ep-example-pooler.region.aws.neon.tech/dbname?sslmode=require
DATABASE_URL_DIRECT=postgresql://user:password@ep-example.region.aws.neon.tech/dbname?sslmode=require
```

The app uses `DATABASE_URL` and requires `sslmode=require`. From `backend-cloud/`, run
`py tools_dev/migrate_neon.py` with `DATABASE_URL_DIRECT` set to the Neon dev branch
when applying schema changes. SQLite remains the local fallback.
ChromaDB has been removed; Neon uses pgvector for semantic memory, with SQL
keyword search retained whenever embeddings or pgvector are unavailable.

Neon is not probed on a timer, so an idle database can suspend. If PostgreSQL
is unavailable during local startup, this process falls back to SQLite; restart
the backend to retry Neon. Production requires `DB_BACKEND=postgres` and refuses
to start on SQLite if PostgreSQL initialization fails, avoiding writes to a
process-local database.

### Per-user data and legacy ownership

Conversations, notes, alarms, memory facts/vectors, monitors and their history,
command logs, events, and snapshots are stored with the authenticated
`owner_username`. Clerk identities use the `clerk:<subject>` namespace; local
accounts keep their local username. Run the ownership assignment script once
for any pre-isolation database. Review the counts first, then repeat without
`--dry-run` to assign unowned rows and legacy SQLite snapshot files:

```powershell
$env:OWNER_USERNAME = "the-owner-identity"
py scripts/assign_legacy_owner.py --dry-run
py scripts/assign_legacy_owner.py
```

For Clerk account deletion, configure the Clerk webhook endpoint as
`/api/webhooks/clerk` and set `CLERK_WEBHOOK_SECRET` in the backend environment.
The endpoint accepts only Svix-signed requests and purges data for the deleted
Clerk subject.

---

## Device gateway (Socket.IO)

Paired PCs connect on namespace `/device` (`wss://` in production).

- **Local Windows:** `py wsgi.py` uses Flask-SocketIO + Werkzeug
  (`allow_unsafe_werkzeug=True`), default bind `127.0.0.1`.
- **Production (Linux):** one Gunicorn threaded worker (multiple workers
  need sticky sessions and a message queue):

```bash
gunicorn --bind "0.0.0.0:${PORT:?PORT must be provided by the host}" \
  --worker-class gthread --threads 100 --workers 1 wsgi:app
```

Pair a device (PIN required): `POST /api/devices/pair` then run
`py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id … --token …`

PowerShell example (token is shown once; do not commit it):

```powershell
$pair = Invoke-RestMethod -Method POST http://127.0.0.1:5000/api/devices/pair `
  -ContentType "application/json" -Body '{"name":"dev-pc","pin":"YOUR_PIN"}'
py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id $pair.device_id --token $pair.token
```

## Validation

Run the real-process smoke check from `backend-cloud/`:

```powershell
.\scripts\smoke_real_start.ps1
```

Run the Electron suites from the repository root:

```powershell
npm --prefix client-electron test
npm --prefix client-electron run test:camera
```

---

## AI Router

Groq (Llama 3.3 70B) → OpenRouter → Gemini  
All workers report back through Groq as manager (JARVIS voice).

---

Built with ❤️ by Hammad
