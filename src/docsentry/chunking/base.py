"""The ``Chunker`` abstraction -- design spec 4.3 and 6.3.

Every strategy takes a ``Document`` and returns ``list[Chunk]``. They share one
``target_size`` and one notion of "how big is a chunk", because the whole point
of the M2 comparison is that the only difference between them is *where* they
cut -- see ``SizeStats``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean, median
from typing import Protocol, runtime_checkable

from docsentry.models import Chunk, Document


def accumulate_paragraphs(text: str, target: int) -> list[str]:
    """Group blank-line-separated paragraphs up to ``target`` characters.

    A paragraph longer than ``target`` is emitted whole: it is one unit, and
    cutting it is exactly what ``fixed`` is here to demonstrate the cost of.
    Joining the pieces with ``\\n\\n`` reproduces the text exactly -- nothing
    is dropped or duplicated.
    """
    if len(text) <= target:
        return [text]
    pieces: list[str] = []
    buffer = ""
    for paragraph in text.split("\n\n"):
        if buffer and len(buffer) + len(paragraph) + 2 > target:
            pieces.append(buffer)
            buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        pieces.append(buffer)
    return pieces


_TAG_RE = re.compile(r"<[^>]+>")


def is_noise(text: str) -> bool:
    """True when a chunk carries no retrievable content at all.

    The bar is deliberately narrow: after stripping HTML tags, nothing is left.
    Sampled from the real corpus, sub-200-character sections are mostly
    *useful* -- precise API fragments like "Delete items from vector store"
    (179 characters) are exactly what a developer asks about, so they are kept
    and not merged (design spec 6.3.3 step 8). The genuinely empty ones are the
    handful whose whole body is a layout artefact such as
    ``<div id="enable-section-numbers" />``.

    A heuristic that also dropped "short" text would have to pick a threshold,
    and every threshold in the 100-500 range throws away chunks the sample shows
    to be good. "Empty after stripping tags" needs no threshold.
    """
    return not _TAG_RE.sub("", text).strip()


@dataclass
class SizeStats:
    """What the fairness report publishes -- design spec 6.3.

    ``total_chars`` is here because it is the number that exposes the overlap
    difference: ``fixed`` indexes 1.25x the corpus, the structure-aware
    strategies 1.00x. Mean size alone would hide it.
    """

    count: int
    mean: float
    median: float
    total_chars: int

    @classmethod
    def from_sizes(cls, sizes: list[int]) -> SizeStats:
        if not sizes:
            return cls(count=0, mean=0.0, median=0.0, total_chars=0)
        return cls(count=len(sizes), mean=mean(sizes), median=median(sizes),
                   total_chars=sum(sizes))


@runtime_checkable
class Chunker(Protocol):
    """One chunking strategy.

    Runtime note: ``isinstance`` works structurally -- members are checked by
    *presence*, not by signature. ``issubclass`` does not: Python raises
    ``TypeError`` for runtime protocols with data members such as ``name``
    (same behaviour as the corpus-layer ``Source`` protocol). The strategies
    are dispatched with ``isinstance``; never use ``issubclass`` here.
    """

    name: str

    def chunk(self, doc: Document) -> list[Chunk]:
        """Split one document. ``Document.indexed_at`` is ``None`` at this stage."""
        ...
