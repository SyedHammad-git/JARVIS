"""
J.A.R.V.I.S v18 — Episodic Memory (STUB)
Long-term storage of past interactions with temporal context.
Backed by SQLite (existing conversations table) + optional vector index.
"""

class EpisodicMemory:
    def recall(self, query: str, top_k: int = 5) -> list:
        """Retrieve relevant past episodes. (NOT YET IMPLEMENTED)"""
        raise NotImplementedError("EpisodicMemory.recall() — v18 TODO")

    def store(self, episode: dict): ...
