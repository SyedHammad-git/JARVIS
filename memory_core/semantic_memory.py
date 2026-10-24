"""
J.A.R.V.I.S v18 — Semantic Memory (STUB)
Factual knowledge base (wraps existing memory_facts table).
v18 will add vector embeddings via ChromaDB.
"""

class SemanticMemory:
    def lookup(self, concept: str) -> list:
        """Find facts related to concept. (NOT YET IMPLEMENTED)"""
        raise NotImplementedError("SemanticMemory.lookup() — v18 TODO")

    def store_fact(self, fact: str, category: str = "general"): ...
