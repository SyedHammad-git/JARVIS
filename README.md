# J.A.R.V.I.S v17.M — Modular Edition

**Just A Rather Very Intelligent System**  
Built by Hammad • Iron Man Edition

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up .env
cp .env .env.local
# Edit .env — add your API keys

# 3. Run
python server.py
```

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
├── vector/                ← v18 stub — ChromaDB client
├── JARVIS.html            ← Desktop UI
└── mobile.html            ← Mobile UI
```

---

## Database Switch

```env
# Local dev (default — zero config):
DB_BACKEND=sqlite

# Production Supabase:
DB_BACKEND=postgres
POSTGRES_DSN=postgresql://postgres:PASSWORD@db.REF.supabase.co:5432/postgres
```

Switch = change 1 env variable. Zero code changes.

---

## AI Router

Groq (Llama 3.3 70B) → OpenRouter → Gemini  
All workers report back through Groq as manager (JARVIS voice).

---

Built with ❤️ by Hammad
