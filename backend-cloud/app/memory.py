"""J.A.R.V.I.S v17.M — Memory Module"""
import logging
from app.db import db_read, db_write, ts
from app.auth import add_alert
from app.ai.engine import build_jarvis_context
from app.vector.pg_store import add_memory, delete_memory, search as search_vectors

log = logging.getLogger("jarvis.memory")

def get_facts(category: str = "", owner_username: str = "") -> list:
    if category:
        return db_read("SELECT * FROM memory_facts WHERE owner_username=? AND category=? ORDER BY id DESC",
                       (owner_username, category))
    return db_read("SELECT * FROM memory_facts WHERE owner_username=? ORDER BY last_used DESC LIMIT 50",
                   (owner_username,))

def learn_fact(fact: str, category: str = "general", source: str = "manual",
               owner_username: str = "") -> str:
    now = ts()
    db_write(
        "INSERT INTO memory_facts(owner_username,category,fact,source,created_at,last_used) VALUES(?,?,?,?,?,?)",
        (owner_username, category, fact, source, now, now)
    )
    fact_id = db_read(
        "SELECT id FROM memory_facts WHERE owner_username=? AND fact=? ORDER BY id DESC LIMIT 1",
        (owner_username, fact),
    )
    if fact_id:
        add_memory(str(fact_id[0]["id"]), fact, {"category": category, "source": source}, owner_username)
    add_alert(f"Memory: Learned — {fact[:40]}", owner_username=owner_username)
    return f"Fact stored, Sir: {fact[:60]}"

def search_facts_semantic(query: str, top_k: int = 5, owner_username: str = "") -> list:
    """Semantic search over learned facts. Falls back to a simple keyword
    LIKE search when the vector store is unavailable, so callers always
    get a usable result either way rather than needing to branch on
    whether semantic search happened to work this time."""
    hits = search_vectors(query, top_k=top_k, owner_username=owner_username)
    if hits:
        return [{"fact": h["text"], "category": h["metadata"].get("category", ""),
                 "relevance": 1 - min(h["distance"], 1.0)} for h in hits]
    like_hits = db_read(
        "SELECT fact, category FROM memory_facts WHERE owner_username=? AND fact LIKE ? ORDER BY last_used DESC LIMIT ?",
        (owner_username, f"%{query}%", top_k)
    )
    return [{"fact": r["fact"], "category": r["category"], "relevance": None} for r in like_hits]

def forget_fact(fact_id, owner_username: str = "") -> bool:
    if fact_id:
        deleted = db_write("DELETE FROM memory_facts WHERE id=? AND owner_username=?", (fact_id, owner_username))
        if deleted:
            delete_memory(str(fact_id), owner_username)
        return deleted
    return False

def get_context(owner_username: str = "") -> str:
    return build_jarvis_context(owner_username)

def touch_fact(fact_id, owner_username: str = ""):
    db_write("UPDATE memory_facts SET last_used=? WHERE id=? AND owner_username=?",
             (ts(), fact_id, owner_username))

# ── Conversation persistence — used by agent.py so the orchestrator
# doesn't hold raw SQL inline. Wraps the existing `conversations` table
# (unchanged schema/columns) that was already there and already working;
# this is purely an extraction, not a new table or a behavior change. ──
def load_recent_messages(session_id: str, limit: int = 10, owner_username: str = "") -> list:
    """Last `limit` messages for a session, oldest first — hydrates the
    LLM's context window at the start of an agent turn."""
    rows = db_read(
        "SELECT role,content FROM conversations WHERE owner_username=? AND session_id=? ORDER BY id DESC LIMIT ?",
        (owner_username, session_id, limit)
    )
    return list(reversed(rows))

def save_message(session_id: str, role: str, content: str,
                 tools_used: str = "", ai_model: str = "", owner_username: str = "") -> bool:
    """Persist one message to conversation history."""
    return db_write(
        "INSERT INTO conversations(owner_username,session_id,role,content,created_at,tools_used,ai_model)"
        " VALUES(?,?,?,?,?,?,?)",
        (owner_username, session_id, role, content, ts(), tools_used, ai_model)
    )

def prune_conversation(session_id: str, keep_last: int = 100, owner_username: str = "") -> bool:
    """Trim a session's history to the most recent `keep_last` messages so
    a long-running session doesn't grow the table unbounded."""
    return db_write(
        "DELETE FROM conversations WHERE owner_username=? AND session_id=? AND id NOT IN"
        "(SELECT id FROM conversations WHERE owner_username=? AND session_id=? ORDER BY id DESC LIMIT ?)",
        (owner_username, session_id, owner_username, session_id, keep_last)
    )
