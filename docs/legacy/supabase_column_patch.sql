-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  J.A.R.V.I.S — Supabase Column Sync Patch                          ║
-- ║  Run this ONCE in Supabase SQL Editor to match Python code columns  ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- The Python code now uses created_at everywhere.
-- These statements add created_at aliases if your Supabase tables 
-- use different column names from the initial deploy.

-- CONVERSATIONS: add created_at if column was named differently
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='created_at'
  ) THEN
    ALTER TABLE conversations ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- MEMORY_FACTS: add created_at
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='memory_facts' AND column_name='created_at'
  ) THEN
    ALTER TABLE memory_facts ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- ALARMS: add created_at + repeat column
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='alarms' AND column_name='created_at'
  ) THEN
    ALTER TABLE alarms ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='alarms' AND column_name='repeat'
  ) THEN
    ALTER TABLE alarms ADD COLUMN repeat TEXT DEFAULT 'once';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='alarms' AND column_name='status'
  ) THEN
    ALTER TABLE alarms ADD COLUMN status TEXT DEFAULT 'pending';
  END IF;
END $$;

-- COMMAND_LOG: add created_at
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='command_log' AND column_name='created_at'
  ) THEN
    ALTER TABLE command_log ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- EVENTS: add created_at
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='events' AND column_name='created_at'
  ) THEN
    ALTER TABLE events ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
  -- events table might not exist — create it
  CREATE TABLE IF NOT EXISTS events (
    id         SERIAL PRIMARY KEY,
    type       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
END $$;

-- HEARTBEAT_LOG: ensure created_at exists  
CREATE TABLE IF NOT EXISTS heartbeat_log (
  id         SERIAL PRIMARY KEY,
  trigger    TEXT NOT NULL,
  message    TEXT NOT NULL,
  priority   TEXT DEFAULT 'medium',
  delivered  BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CONFIG: ensure updated_at exists (not 'updated')
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='config' AND column_name='updated_at'
  ) THEN
    ALTER TABLE config ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- MONITORS: ensure created_at exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='monitors' AND column_name='created_at'
  ) THEN
    ALTER TABLE monitors ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- SESSION_STATS table
CREATE TABLE IF NOT EXISTS session_stats (
  id              SERIAL PRIMARY KEY,
  date            DATE NOT NULL,
  active_minutes  INTEGER DEFAULT 0,
  commands_given  INTEGER DEFAULT 0,
  ai_calls        INTEGER DEFAULT 0,
  break_reminders INTEGER DEFAULT 0,
  last_active     TIMESTAMPTZ
);

-- CAMERAS table
CREATE TABLE IF NOT EXISTS cameras (
  id     SERIAL PRIMARY KEY,
  name   TEXT NOT NULL DEFAULT 'Camera',
  source TEXT NOT NULL DEFAULT '0',
  active BOOLEAN NOT NULL DEFAULT FALSE
);

-- ✅ Verify: show all tables
SELECT table_name, 
       (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) as col_count
FROM information_schema.tables t
WHERE table_schema = 'public'
ORDER BY table_name;

-- ── CONVERSATIONS TABLE FIX ─────────────────────────────────────
-- Python code inserts: session_id, role, content, created_at, tools_used, ai_model
-- Supabase default has: user_id, title, summary (MISMATCH → ALL chat inserts fail!)
-- Solution: add missing columns so both old and new structure coexist

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='session_id'
  ) THEN
    ALTER TABLE conversations ADD COLUMN session_id TEXT DEFAULT 'default';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='role'
  ) THEN
    ALTER TABLE conversations ADD COLUMN role TEXT DEFAULT 'user';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='content'
  ) THEN
    ALTER TABLE conversations ADD COLUMN content TEXT DEFAULT '';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='tools_used'
  ) THEN
    ALTER TABLE conversations ADD COLUMN tools_used TEXT DEFAULT '';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='conversations' AND column_name='ai_model'
  ) THEN
    ALTER TABLE conversations ADD COLUMN ai_model TEXT DEFAULT 'groq';
  END IF;
END $$;

-- MEMORY_FACTS: ensure all Python columns exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='memory_facts' AND column_name='last_used'
  ) THEN
    ALTER TABLE memory_facts ADD COLUMN last_used TEXT DEFAULT '';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='memory_facts' AND column_name='source'
  ) THEN
    ALTER TABLE memory_facts ADD COLUMN source TEXT DEFAULT 'learned';
  END IF;
END $$;

-- EVENTS table (may not exist on Supabase)
CREATE TABLE IF NOT EXISTS events (
  id         BIGSERIAL PRIMARY KEY,
  type       TEXT NOT NULL,
  message    TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- COMMAND_LOG: ensure Python columns exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='command_log' AND column_name='remote'
  ) THEN
    ALTER TABLE command_log ADD COLUMN remote INTEGER DEFAULT 0;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='command_log' AND column_name='result'
  ) THEN
    ALTER TABLE command_log ADD COLUMN result TEXT DEFAULT '';
  END IF;
END $$;

-- NOTES: ensure updated_at exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='notes' AND column_name='updated_at'
  ) THEN
    ALTER TABLE notes ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- ALARMS: ensure all columns exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='alarms' AND column_name='time'
  ) THEN
    ALTER TABLE alarms ADD COLUMN time TEXT DEFAULT '00:00';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='alarms' AND column_name='retry_count'
  ) THEN
    ALTER TABLE alarms ADD COLUMN retry_count INTEGER DEFAULT 0;
  END IF;
END $$;

-- ✅ Final verification
SELECT
  table_name,
  COUNT(*) as columns
FROM information_schema.columns
WHERE table_schema = 'public'
GROUP BY table_name
ORDER BY table_name;
