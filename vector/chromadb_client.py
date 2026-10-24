"""
J.A.R.V.I.S v17.M — ChromaDB Vector Store Client

Implements the VectorStore interface (previously a v18 stub) for semantic
similarity search over JARVIS memory facts.

Graceful degradation: chromadb's default embedding function downloads a
~90MB ONNX model from S3 on first use — confirmed during development that
this download can fail in a network-restricted environment (SHA256
mismatch on a truncated download). Every method here is wrapped so that
ANY failure — import error, download failure, corrupted local cache,
version mismatch — leaves the store in a disabled state (`ok=False`)
instead of raising. Callers (memory.py) always get a bool/list back and
never need their own try/except around this module.
"""
import logging

log = logging.getLogger("jarvis.vector")

try:
    import chromadb
    _CHROMADB_IMPORT_OK = True
except Exception as e:
    chromadb = None
    _CHROMADB_IMPORT_OK = False
    log.warning("chromadb not installed (%s) — semantic memory search disabled, "
                "falling back to keyword-only search.", e)


class VectorStore:
    """Semantic similarity search over a named collection. Safe to
    instantiate even when chromadb is unavailable or fails to initialize —
    check `.ok` (or just call the methods; they degrade to no-ops/empty
    results on their own)."""

    def __init__(self, collection: str = "jarvis_memory", persist_dir=None):
        self._collection_name = collection
        self._client     = None
        self._collection  = None
        self.ok           = False
        self.disabled_reason = None

        if not _CHROMADB_IMPORT_OK:
            self.disabled_reason = "chromadb not installed"
            return

        try:
            if persist_dir is None:
                # Deliberately not imported from database.py at module
                # load time, to avoid this module (imported lazily, well
                # after server startup) having any bearing on server.py's
                # early-boot import ordering — but resolved dynamically
                # here, at construction time, which is always safe.
                from database import HOME
                persist_dir = HOME / "JARVIS_Data" / "vector_db"
            self._client    = chromadb.PersistentClient(path=str(persist_dir))
            self._collection = self._client.get_or_create_collection(collection)
            self.ok = True
            log.info("VectorStore ready: collection=%s dir=%s", collection, persist_dir)
        except Exception as e:
            self.disabled_reason = str(e)
            log.warning("VectorStore init failed (%s) — semantic memory search "
                       "disabled, falling back to keyword-only search.", e)

    def upsert(self, doc_id: str, text: str, metadata: dict = None) -> bool:
        """Index (or re-index) one piece of text. Returns False on any
        failure instead of raising — the caller's SQLite write (the
        source of truth) already succeeded independently of this."""
        if not self.ok:
            return False
        try:
            kwargs = {"ids": [str(doc_id)], "documents": [text]}
            if metadata:   # chromadb rejects an empty-but-present metadata dict
                kwargs["metadatas"] = [metadata]
            self._collection.upsert(**kwargs)
            return True
        except Exception as e:
            log.warning("VectorStore.upsert failed for %r: %s — disabling for "
                       "the rest of this process (won't keep retrying a slow "
                       "failing embedding call on every future request).", doc_id, e)
            self.ok = True if False else False   # explicit for readability
            self.ok = False
            self.disabled_reason = str(e)
            return False

    def query(self, text: str, top_k: int = 5) -> list:
        """Return up to top_k semantically similar documents as
        [{"id":.., "text":.., "metadata":.., "distance":..}, ...].
        Returns [] on any failure or when unavailable — treat that the
        same as "no matches", not as an error."""
        if not self.ok:
            return []
        try:
            r = self._collection.query(query_texts=[text], n_results=top_k)
            ids   = (r.get("ids")       or [[]])[0]
            docs  = (r.get("documents") or [[]])[0]
            metas = (r.get("metadatas") or [[]])[0]
            dists = (r.get("distances") or [[]])[0]
            return [{"id": i, "text": d, "metadata": m, "distance": dist}
                    for i, d, m, dist in zip(ids, docs, metas, dists)]
        except Exception as e:
            log.warning("VectorStore.query failed for %r: %s — disabling for "
                       "the rest of this process.", text, e)
            self.ok = False
            self.disabled_reason = str(e)
            return []

    def delete(self, doc_id: str) -> bool:
        if not self.ok:
            return False
        try:
            self._collection.delete(ids=[str(doc_id)])
            return True
        except Exception as e:
            log.warning("VectorStore.delete failed for %r: %s", doc_id, e)
            return False
