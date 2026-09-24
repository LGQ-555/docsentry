"""The ``Chunker`` abstraction -- design spec 4.3 and 6.3.

Every strategy takes a ``Document`` and returns ``list[Chunk]``. They share one
``target_size`` and one notion of "how big is a chunk", because the whole point
of the M2 comparison is that the only difference between them is *where* they
cut -- see ``SizeStats``.

Since Task 12b this module also hosts decision 2's forced-degradation helpers
(``segment_blocks`` / ``block_kind`` / ``cut_atomic``): the
``max_atomic_size`` ceiling is a *system* rule about what can be embedded at
all, not a feature of the ``structural`` strategy, so both structure-aware
chunkers consume these from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean, median
from typing import Protocol, runtime_checkable

from docsentry.config import ChunkingConfig
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


# Same fence heuristic as structural's ``_classify`` -- indented openers count,
# info strings containing a backtick mis-toggle. Accepted divergence, damage
# bounded to a misclassified block. ``_TOP_LEVEL_RE`` and ``_DELIM_RE`` are
# the cut-point heuristics of decision 2's forced degradation; they have no
# consumer outside ``cut_atomic``, so they stay module-private here.
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_TOP_LEVEL_RE = re.compile(r"^(def |class |function |async def |async function )")
_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def segment_blocks(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(kind, block)`` where kind is code | table | prose.

    The boundaries are the structural ones, so a block is the unit the
    chunkers pack and never cut inside:

    * blank lines, as in the paragraph accumulators;
    * fence lines, which are unambiguous block boundaries in Markdown --
      prose glued to a closing fence (no blank line) must not ride into the
      code block, or ``cut_atomic`` would cut it as code;
    * pipe-line runs: a table glued to a following paragraph must not make
      the paragraph a table row, or every piece of a forced cut would repeat
      the header over prose.

    The fence scan is the same heuristic as structural's ``_classify`` with
    the same accepted divergences (a fence shown *inside* a fence toggles it
    shut). The damage is a block misclassified around the glitch -- never
    lost or moved content, because the lines themselves always land in some
    block.
    """
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append((block_kind(current), "".join(current)))
            current.clear()

    for line in text.splitlines(keepends=True):
        if FENCE_RE.match(line):
            if in_fence:
                current.append(line)
                flush()
                in_fence = False
            else:
                flush()
                current.append(line)
                in_fence = True
            continue
        if not in_fence and not line.strip():
            flush()
            continue
        if (not in_fence and current
                and current[0].lstrip().startswith("|") != line.lstrip().startswith("|")):
            flush()
        current.append(line)
    flush()
    return [(k, b) for k, b in blocks if b.strip()]


def block_kind(lines: list[str]) -> str:
    """Classify one block by its first line. Load-bearing on
    ``segment_blocks``'s splits: a code block starts with its opener (fence
    split), a table block contains only pipe lines (pipe split), everything
    else is prose."""
    joined = "".join(lines).lstrip()
    if joined.startswith(("```", "~~~")):
        return "code"
    if joined.startswith("|"):
        return "table"
    return "prose"


def cut_atomic(kind: str, block: str, config: ChunkingConfig) -> list[str]:
    """Cut one unit that exceeded ``max_atomic_size`` -- decision 2's forced
    degradation. Callers flag every returned piece ``split_atomic=True``.

    * Table: rows are the unit, so the cut lands between rows; each piece
      repeats the header row + delimiter row, without which a piece of a
      table is unreadable. ``lines[:2]`` is the header only when the second
      line really is a delimiter row -- measured on the 2026-09-24 corpus
      every oversized table block has exactly that shape, and the guard
      keeps a pipe-listing (or a one-line block) from losing rows or
      duplicating data rows as "header". A row longer than the budget is cut
      mid-row rather than left to exceed the ceiling.
    * Code: pack to the budget; when a line would exceed it, back up to the
      most recent top-level ``def`` / ``class`` / ``function`` line so the
      cut lands between constructs. Without such a boundary in reach (one
      unbroken run) the cut is mid-construct -- which is exactly why the
      pieces are flagged. A single line longer than the whole budget is cut
      mid-line. The budget is ``max_code_size`` capped by
      ``max_atomic_size``: the ceiling must hold even under a config that
      puts the granularity above it.
    * Prose: an unbroken run has no boundaries at all, so plain hard cuts;
      a line longer than the ceiling is cut mid-line.
    """
    ceiling = config.max_atomic_size
    lines = block.splitlines(keepends=True)

    if kind == "table":
        budget = min(config.target_size, ceiling)
        if len(lines) >= 3 and _DELIM_RE.match(lines[1]):
            header, rows = lines[:2], lines[2:]
        else:
            header, rows = [], lines
        pieces: list[str] = []
        buffer: list[str] = []
        size = len("".join(header))
        for row in rows:
            while len(row) > budget:
                pieces.append("".join(header + [row[:budget]]))
                row = row[budget:]
            if buffer and size + len(row) > budget:
                pieces.append("".join(header + buffer))
                buffer, size = [], len("".join(header))
            buffer.append(row)
            size += len(row)
        if buffer:
            pieces.append("".join(header + buffer))
        return pieces

    if kind == "code":
        budget = min(config.max_code_size, ceiling)
        pieces: list[str] = []
        buffer: list[str] = []
        size = 0
        last_boundary = 0
        for line in lines:
            if len(line) > budget:
                # A line longer than the whole budget (a minified blob or a
                # log dump -- measured inside unclosed-fence blocks): no
                # boundary can save it, so cut mid-line. The first slice
                # rides with the flushed buffer so a lone fence opener does
                # not become its own piece.
                head = "".join(buffer)
                buffer, size, last_boundary = [], 0, 0
                rest = line
                while len(rest) > budget:
                    take = max(budget - len(head), 1) if head else budget
                    pieces.append(head + rest[:take])
                    rest, head = rest[take:], ""
                line = head + rest if head else rest
            if buffer and size + len(line) > budget:
                if last_boundary > 0:
                    pieces.append("".join(buffer[:last_boundary]))
                    buffer = buffer[last_boundary:]
                    size = sum(len(l) for l in buffer)
                    last_boundary = 0
                else:
                    pieces.append("".join(buffer))
                    buffer, size = [], 0
            if _TOP_LEVEL_RE.match(line):
                last_boundary = len(buffer)
            buffer.append(line)
            size += len(line)
        if buffer:
            pieces.append("".join(buffer))
        return pieces

    # prose
    pieces: list[str] = []
    rest = block
    while len(rest) > ceiling:
        cut = rest.rfind("\n", 0, ceiling)
        if cut < 0:
            cut = ceiling
            pieces.append(rest[:cut])
            rest = rest[cut:]
        else:
            pieces.append(rest[:cut])
            rest = rest[cut + 1:]
    if rest:
        pieces.append(rest)
    return pieces


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
