"""Mocked Gemini embedding and pgvector store tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import memory
import database
import scripts.backfill_vectors as backfill_vectors
import vector.pg_store as pg_store


def test_gemini_embedding_uses_768_dimensions_without_logging_secrets(monkeypatch):
    key = "mock-gemini-secret"
    values = [0.25] * pg_store.EMBEDDING_DIMENSIONS
    request = Mock(return_value=SimpleNamespace(
        status_code=200,
        json=lambda: {"embedding": {"values": values}},
    ))
    monkeypatch.setattr(pg_store, "GEMINI_KEY", key)
    monkeypatch.setattr(pg_store, "REQUESTS_OK", True)
    monkeypatch.setattr(pg_store, "_req", SimpleNamespace(post=request))

    result = pg_store.embed_text("a searchable memory")

    assert result == values
    assert request.call_args.kwargs["json"]["outputDimensionality"] == 768
    assert key not in repr(request.call_args.kwargs["json"])


def test_embedding_failure_degrades_without_exception(monkeypatch):
    monkeypatch.setattr(pg_store, "GEMINI_KEY", "present-but-not-logged")
    monkeypatch.setattr(pg_store, "REQUESTS_OK", True)
    monkeypatch.setattr(pg_store, "_req", SimpleNamespace(post=Mock(side_effect=TimeoutError())))
    assert pg_store.embed_text("query") is None


def test_add_memory_writes_json_and_vector_only_in_postgres(monkeypatch):
    vector = [0.125] * pg_store.EMBEDDING_DIMENSIONS
    write = Mock(return_value=True)
    monkeypatch.setattr(pg_store, "DB_BACKEND", "postgres")
    monkeypatch.setattr(pg_store, "embed_text", lambda _text: vector)
    monkeypatch.setattr(pg_store, "db_write", write)

    assert pg_store.add_memory("fact-7", "fact text", {"category": "general"})
    sql, params = write.call_args.args
    assert "INSERT INTO memory_vectors" in sql
    assert params[0:3] == ("fact-7", "fact text", json.dumps({"category": "general"}))
    assert params[3].startswith("[") and params[3].endswith("]")


def test_search_returns_empty_when_embeddings_unavailable(monkeypatch):
    read = Mock()
    monkeypatch.setattr(pg_store, "DB_BACKEND", "postgres")
    monkeypatch.setattr(pg_store, "embed_text", lambda _text: None)
    monkeypatch.setattr(pg_store, "db_read", read)

    assert pg_store.search("query") == []
    read.assert_not_called()


def test_search_maps_pgvector_results(monkeypatch):
    monkeypatch.setattr(pg_store, "DB_BACKEND", "postgres")
    monkeypatch.setattr(pg_store, "embed_text", lambda _text: [0.5] * 768)
    monkeypatch.setattr(pg_store, "db_read", lambda _sql, _params: [{
        "id": "fact-1", "content": "desk fact", "meta": {"category": "general"}, "distance": 0.1,
    }])

    assert pg_store.search("desk") == [{
        "id": "fact-1", "text": "desk fact", "metadata": {"category": "general"}, "distance": 0.1,
    }]


def test_memory_keeps_keyword_fallback_when_pgvector_returns_no_hits(monkeypatch):
    monkeypatch.setattr(memory, "search_vectors", lambda _query, top_k=5: [])
    monkeypatch.setattr(memory, "db_read", lambda _sql, params: [{"fact": "desk fact", "category": "general"}])

    assert memory.search_facts_semantic("desk") == [
        {"fact": "desk fact", "category": "general", "relevance": None}
    ]


def test_backfill_uses_postgres_fact_rows_and_pg_store(monkeypatch, capsys):
    writes = []
    fake_database = SimpleNamespace(DB_BACKEND="postgres", db_read=lambda _sql, _params: [{
        "id": 9, "fact": "fact text", "category": "general", "source": "manual",
    }])
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://direct@ep-dev.neon.tech/app")
    monkeypatch.setenv("DATABASE_URL", "postgresql://pooler@ep-prod-pooler.neon.tech/app")
    monkeypatch.setattr(backfill_vectors, "_load_database", lambda: fake_database)
    monkeypatch.setattr(backfill_vectors, "_add_memory", lambda *args: writes.append(args) or True)

    assert backfill_vectors.main(["--limit", "2"]) == 0
    assert "ep-dev.neon.tech" in __import__("os").environ["DATABASE_URL"]
    assert writes == [("9", "fact text", {"category": "general", "source": "manual"})]
    assert "indexed=1" in capsys.readouterr().out
