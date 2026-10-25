"""Neon pgvector memory store; failures degrade to keyword search."""
from __future__ import annotations

import json
import math

from app.config import REQUESTS_OK, _req, get_api_key
from app.db import DB_BACKEND, db_read, db_write

EMBEDDING_DIMENSIONS = 768
EMBEDDING_MODEL = "gemini-embedding-001"


def embed_text(text: str) -> list[float] | None:
    gemini_key = get_api_key("GEMINI_KEY")
    if not REQUESTS_OK or not gemini_key or not isinstance(text, str) or not text.strip():
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{EMBEDDING_MODEL}:embedContent?key={gemini_key}"
    )
    payload = {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {"parts": [{"text": text[:8000]}]},
        "outputDimensionality": EMBEDDING_DIMENSIONS,
    }
    try:
        response = _req.post(url, json=payload, timeout=20)
        if response.status_code != 200:
            return None
        values = response.json().get("embedding", {}).get("values")
        if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS:
            return None
        vector = [float(value) for value in values]
        return vector if all(math.isfinite(value) for value in vector) else None
    except Exception:
        return None


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(format(value, ".8g") for value in embedding) + "]"


def add_memory(memory_id: str, content: str, meta: dict | None = None) -> bool:
    if DB_BACKEND != "postgres":
        return False
    embedding = embed_text(content)
    if embedding is None:
        return False
    return db_write(
        "INSERT INTO memory_vectors(id,content,meta,embedding) VALUES(?,?,?::jsonb,?::vector) "
        "ON CONFLICT(id) DO UPDATE SET content=EXCLUDED.content,meta=EXCLUDED.meta,embedding=EXCLUDED.embedding",
        (str(memory_id), content, json.dumps(meta or {}), _vector_literal(embedding)),
    )


def search(query: str, top_k: int = 5) -> list[dict]:
    if DB_BACKEND != "postgres":
        return []
    embedding = embed_text(query)
    if embedding is None:
        return []
    vector = _vector_literal(embedding)
    rows = db_read(
        "SELECT id,content,meta,(embedding <=> ?::vector) AS distance "
        "FROM memory_vectors ORDER BY embedding <=> ?::vector LIMIT ?",
        (vector, vector, max(1, min(int(top_k), 50))),
    )
    return [
        {
            "id": row.get("id"),
            "text": row.get("content", ""),
            "metadata": row.get("meta") or {},
            "distance": float(row.get("distance") or 0),
        }
        for row in rows
    ]


def delete_memory(memory_id: str) -> bool:
    if DB_BACKEND != "postgres":
        return False
    return db_write("DELETE FROM memory_vectors WHERE id=?", (str(memory_id),))
