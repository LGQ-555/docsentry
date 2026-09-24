"""Strategy name -> chunker. One place so the CLI, the indexer and the fairness
check cannot drift apart on what the strategies are called."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docsentry.chunking.fixed import FixedSizeChunker
from docsentry.chunking.semantic import SemanticChunker
from docsentry.chunking.structural import StructuralChunker
from docsentry.config import ChunkingConfig

if TYPE_CHECKING:
    # Annotation-only: ``from __future__ import annotations`` turns the return
    # annotation into a string that is never evaluated, so importing the
    # runtime-checkable Protocol here would pay its protocol-member
    # computation for nothing. No ``isinstance`` check lives in this module.
    from docsentry.chunking.base import Chunker

STRATEGIES: dict[str, type] = {
    "fixed": FixedSizeChunker,
    "semantic": SemanticChunker,
    "structural": StructuralChunker,
}


def build_chunker(name: str, config: ChunkingConfig) -> Chunker:
    return STRATEGIES[name](config)
