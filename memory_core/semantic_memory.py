"""J.A.R.V.I.S semantic-memory facade (legacy stub)."""

class SemanticMemory:
    def lookup(self, concept: str) -> list:
        """Find facts related to concept. (NOT YET IMPLEMENTED)"""
        raise NotImplementedError("SemanticMemory.lookup() — v18 TODO")

    def store_fact(self, fact: str, category: str = "general"): ...
