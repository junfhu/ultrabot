"""Memory & Context Engine for ultrabot."""

from ultrabot.memory.store import ContextEngine, MemoryStore

__all__ = ["MemoryStore", "ContextEngine", "MemoryAutoExtractor"]


def __getattr__(name: str):
    if name == "MemoryAutoExtractor":
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        return MemoryAutoExtractor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
