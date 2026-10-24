"""J.A.R.V.I.S v17.M — Memory Module"""
import logging
from database import db_read, db_write, ts
from auth import add_alert
from ai_engine import build_jarvis_context
from vector import VectorStore

log = logging.getLogger("jarvis.memory")

# Constructed once at import time; every method degrades gracefully on its
# own if chromadb isn't installed or its embedding model can't be reached,
# so nothing here needs its own try/except around vector store calls.
_vector_store = VectorStore(collection="jarvis_memory_facts")

def get_facts(category: str = "") -> list:
    if category:
        return db_read("SELECT * FROM memory_facts WHERE category=? ORDER BY id DESC",(category,))
    return db_read("SELECT * FROM memory_facts ORDER BY last_used DESC LIMIT 50")

def learn_fact(fact: str, category: str = "general", source: str = "manual") -> str:
    now = ts()
    db_write(
        "INSERT INTO memory_facts(category,fact,source,created_at,last_used) VALUES(?,?,?,?,?)",
        (category, fact, source, now, now)
    )
    # Best-effort semantic indexing — SQLite above is the source of truth
    # and has already succeeded regardless of whether this does.
    fact_id = db_read("SELECT id FROM memory_facts WHERE fact=? ORDER BY id DESC LIMIT 1", (fact,))
    if fact_id:
        _vector_store.upsert(str(fact_id[0]["id"]), fact, {"category": category, "source": source})
    add_alert(f"Memory: Learned — {fact[:40]}")
    return f"Fact stored, Sir: {fact[:60]}"

def search_facts_semantic(query: str, top_k: int = 5) -> list:
    """Semantic search over learned facts. Falls back to a simple keyword
    LIKE search when the vector store is unavailable, so callers always
    get a usable result either way rather than needing to branch on
    whether semantic search happened to work this time."""
    hits = _vector_store.query(query, top_k=top_k)
    if hits:
        return [{"fact": h["text"], "category": h["metadata"].get("category", ""),
                 "relevance": 1 - min(h["distance"], 1.0)} for h in hits]
    like_hits = db_read(
        "SELECT fact, category FROM memory_facts WHERE fact LIKE ? ORDER BY last_used DESC LIMIT ?",
        (f"%{query}%", top_k)
    )
    return [{"fact": r["fact"], "category": r["category"], "relevance": None} for r in like_hits]

def forget_fact(fact_id) -> bool:
    if fact_id:
        db_write("DELETE FROM memory_facts WHERE id=?", (fact_id,))
        _vector_store.delete(str(fact_id))
        return True
    return False

def get_context() -> str:
    return build_jarvis_context()

def touch_fact(fact_id):
    db_write("UPDATE memory_facts SET last_used=? WHERE id=?", (ts(), fact_id))

# ── Conversation persistence — used by agent.py so the orchestrator
# doesn't hold raw SQL inline. Wraps the existing `conversations` table
# (unchanged schema/columns) that was already there and already working;
# this is purely an extraction, not a new table or a behavior change. ──
def load_recent_messages(session_id: str, limit: int = 10) -> list:
    """Last `limit` messages for a session, oldest first — hydrates the
    LLM's context window at the start of an agent turn."""
    rows = db_read(
        "SELECT role,content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit)
    )
    return list(reversed(rows))

def save_message(session_id: str, role: str, content: str,
                 tools_used: str = "", ai_model: str = "") -> bool:
    """Persist one message to conversation history."""
    return db_write(
        "INSERT INTO conversations(session_id,role,content,created_at,tools_used,ai_model)"
        " VALUES(?,?,?,?,?,?)",
        (session_id, role, content, ts(), tools_used, ai_model)
    )

def prune_conversation(session_id: str, keep_last: int = 100) -> bool:
    """Trim a session's history to the most recent `keep_last` messages so
    a long-running session doesn't grow the table unbounded."""
    return db_write(
        "DELETE FROM conversations WHERE session_id=? AND id NOT IN"
        "(SELECT id FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?)",
        (session_id, session_id, keep_last)
    )
