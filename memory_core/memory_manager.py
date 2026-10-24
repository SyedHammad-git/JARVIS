"""
J.A.R.V.I.S v18 — Memory Manager (STUB)
Unified interface over working, episodic, and semantic memory.
Decides which memory tier to query/update based on recency and relevance.
"""
from memory_core.working_memory  import WorkingMemory
from memory_core.episodic_memory import EpisodicMemory
from memory_core.semantic_memory import SemanticMemory

class MemoryManager:
    def __init__(self):
        self.working  = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

    def query(self, intent: str, context: dict) -> dict:
        """Unified memory query. (NOT YET IMPLEMENTED)"""
        raise NotImplementedError("MemoryManager.query() — v18 TODO")
