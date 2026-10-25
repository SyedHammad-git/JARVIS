# J.A.R.V.I.S v17.M — Modular Edition

**Just A Rather Very Intelligent System**  
Built by Hammad • Iron Man Edition

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up .env
cp .env.example .env
# Edit .env — add your API keys

# 3. Run (production — Waitress WSGI server, 8 threads, binds to 127.0.0.1:5000)
python server.py

# 3b. Run in debug mode (Flask dev server, auto-reload)
set JARVIS_DEBUG=true && python server.py
```

> **Server**: JARVIS uses [Waitress](https://docs.pylonsproject.org/projects/waitress/) in
> production mode (`JARVIS_DEBUG=false`, the default). Set `JARVIS_HOST`, `JARVIS_PORT`,
> or `JARVIS_DEBUG` in `.env` to override defaults.

Open: http://localhost:5000  
Mobile: http://localhost:5000/mobile  
Health: http://localhost:5000/api/ping

---

## Architecture

```
JARVIS_v17M/
├── server.py              ← Flask shell (115 lines only)
├── database.py            ← DB abstraction (SQLite + PostgreSQL)
├── config.py              ← All keys, locks, shared state
├── ai_engine.py           ← Groq + Gemini + OpenRouter
├── tools.py               ← 16 agent tools
├── agent.py               ← ReAct agent loop
├── command.py             ← Quick command router
├── neural.py              ← Neural mode + heartbeat
├── monitor.py             ← System stats + camera
├── smarthome.py           ← Tuya + MQTT
├── memory.py              ← Long-term memory
├── auth.py                ← PIN + security
├── notifications.py       ← Discord + OS alerts
├── routes/
│   ├── core_routes.py     ← /, /mobile, /api/ping, /api/command
│   ├── ai_routes.py       ← /api/agent, /api/neural/*
│   ├── system_routes.py   ← /api/heartbeat, /api/security/*
│   ├── data_routes.py     ← /api/memory/*, /api/notes, /api/alarms
│   └── iot_routes.py      ← /api/smarthome/*, /api/camera/*
├── brain/                 ← v18 stub — BrainOrchestrator
├── agents/                ← v18 stub — MemoryAgent, PlannerAgent
├── memory_core/           ← v18 stub — WorkingMemory, EpisodicMemory
├── planning/              ← v18 stub — Planner
├── learning/              ← v18 stub — Reflection
├── vector/                ← Neon pgvector store with keyword fallback
├── JARVIS.html            ← Desktop UI
└── mobile.html            ← Mobile UI
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

The app uses `DATABASE_URL` and requires `sslmode=require`. Run
`py tools_dev/migrate_neon.py` with `DATABASE_URL_DIRECT` set to the Neon dev
branch when applying schema changes. SQLite remains the local fallback.
ChromaDB has been removed; Neon uses pgvector for semantic memory, with SQL
keyword search retained whenever embeddings or pgvector are unavailable.

---

## Device gateway (Socket.IO)

Paired PCs connect on namespace `/device` (`wss://` in production).

- **Local Windows:** `py server.py` uses Flask-SocketIO + Werkzeug
  (`allow_unsafe_werkzeug=True`), default bind `127.0.0.1`. Waitress cannot
  serve WebSockets — it is used only when `DEVICE_GATEWAY=off`.
- **Production (Linux):** one Gunicorn threaded worker (multiple workers
  need sticky sessions and a message queue):

```bash
gunicorn --worker-class gthread --threads 100 -w 1 server:app
```

Pair a device (PIN required): `POST /api/devices/pair` then run
`py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id … --token …`

PowerShell example (token is shown once; do not commit it):

```powershell
$pair = Invoke-RestMethod -Method POST http://127.0.0.1:5000/api/devices/pair `
  -ContentType "application/json" -Body '{"name":"dev-pc","pin":"YOUR_PIN"}'
py tools_dev/fake_device.py --url http://127.0.0.1:5000 --device-id $pair.device_id --token $pair.token
```

---

## AI Router

Groq (Llama 3.3 70B) → OpenRouter → Gemini  
All workers report back through Groq as manager (JARVIS voice).

---

Built with ❤️ by Hammad
