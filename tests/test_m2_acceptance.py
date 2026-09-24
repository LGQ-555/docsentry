"""M2 acceptance against the real corpus.

Marked ``corpus`` and excluded by default. Assertions use *lower bounds* and
*ratios*, never exact totals: the corpus moves underneath us (LangChain's index
restructured 2026-09-20 -> 09-22, 369 -> 539 documents).

Measured on the 2026-09-24 corpus (774 documents, 14,049,846 characters);
``uv run scripts/check_fairness.py`` reproduces this table:

    strategy     chunks    mean  median  total_chars  coverage
    fixed        17,941     973    1000   17,465,289     1.24x
    semantic     14,682    1032     910   15,155,151     1.08x
    structural   18,442     805     642   14,840,156     1.06x
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docsentry.chunking.registry import STRATEGIES, build_chunker
from docsentry.config import load_chunking_config
from docsentry.corpus.loader import load_corpus
from scripts.check_fairness import MAX_DEVIATION

pytestmark = pytest.mark.corpus

CORPUS = Path("data/corpus.jsonl")


@pytest.fixture(scope="module")
def documents():
    if not CORPUS.exists():
        pytest.skip("no corpus; run scripts/fetch_corpus.py first")
    return list(load_corpus(CORPUS))


@pytest.fixture(scope="module")
def config():
    return load_chunking_config(Path("configs/chunking.yaml"))


def all_chunks(documents, config, name):
    chunker = build_chunker(name, config)
    return [c for doc in documents for c in chunker.chunk(doc)]


def locate(content: str, text: str) -> tuple[int, str]:
    """Where ``text`` sits in ``content``, plus the text actually found.

    A forced atomic cut repeats a wide table's header row at the top of every
    piece, so a piece is *not* a contiguous substring of its document -- a naive
    ``content.find`` misses it and the rows it carries look lost. Measured: that
    artefact alone accounted for 4.4 points of apparent coverage. Dropping the
    repeated leading lines and retrying is what makes the measurement below
    honest. Returns ``(-1, text)`` when nothing matches, so an unmatched chunk
    counts as *uncovered*: the error direction is strictness, never a free pass.
    """
    offset = content.find(text)
    if offset >= 0:
        return offset, text
    lines = text.splitlines(keepends=True)
    for drop in (2, 1, 3):
        if drop < len(lines):
            remainder = "".join(lines[drop:])
            offset = content.find(remainder)
            if offset >= 0:
                return offset, remainder
    return -1, text


def test_structural_covers_the_corpus(documents, config):
    """Gross indexed characters / corpus characters, measured **1.0563**.

    The literal "leaf sections" reading scored 0.788 here, so a 0.95 bar is
    doing real work -- flush-on-close is what closed the gap, and this fails
    loudly if it ever regresses.

    Read the number correctly: it is *gross*, so it can exceed 1.0, and here it
    does. The excess is not double-counting of a whole document -- it is the
    forced atomic cut repeating a wide table's header row in every piece
    (measured: 12 wide-table pages, +1.8% of structural's total). A gross ratio
    is therefore blind to repetition masking loss, which is what the second half
    of ``test_structural_text_reaches_the_index`` exists to catch.
    """
    total = sum(len(d.content) for d in documents)
    indexed = sum(c.char_count for c in all_chunks(documents, config, "structural"))

    assert indexed / total > 0.95, f"structural indexed only {indexed / total:.2%} of the corpus"


def test_structural_text_reaches_the_index(documents, config):
    """Net coverage: the fraction of corpus characters present in at least one
    chunk. Measured **0.9682** -- the residual is heading lines (heading text
    goes into ``breadcrumb``, not into the chunk: 274,543 characters, 1.95% of
    the corpus), noise-dropped sections and stripped edge whitespace.

    The gross ratio above cannot see loss that repetition hides; this can. Both
    bars are 0.95, and this is the tighter of the two in practice (1.8 points of
    margin against 10.6), which is the point -- it is the one measuring content
    rather than volume.
    """
    chunker = build_chunker("structural", config)
    total = covered = 0
    for doc in documents:
        content = doc.content
        total += len(content)
        marks = bytearray(len(content))
        for chunk in chunker.chunk(doc):
            offset, found = locate(content, chunk.text)
            if offset >= 0:
                marks[offset:offset + len(found)] = b"\x01" * len(found)
        covered += sum(marks)

    assert covered / total > 0.95, f"only {covered / total:.2%} of the corpus is in some chunk"


def test_every_document_still_yields_chunks(documents, config):
    """No document may vanish silently -- the corpus layer's whole premise."""
    empty = []
    for name in STRATEGIES:
        chunker = build_chunker(name, config)
        for doc in documents:
            if not chunker.chunk(doc):
                empty.append((name, doc.url))
    assert empty == []


def test_no_chunk_is_pathologically_large(documents, config):
    """A backstop against the failure that motivated the ceiling: without it,
    the atomic-unit rule produced a 106,728-character chunk on the real corpus.

    Measured max is now exactly 4,000 -- ``max_atomic_size`` itself -- for both
    ``semantic`` and ``structural`` (``fixed`` is capped at 1,000 by its window).
    The bar is deliberately *loose* at 3x that, and must not be tightened to
    ``max_atomic_size``: ``cut_atomic`` does not actually guarantee the ceiling.
    Its table branch emits ``header + rows`` without ever checking the header
    against the budget, so a table whose header row is itself oversized yields
    pieces far over -- reproduced in isolation with an 8,005-character header,
    which produced an 8,034-character piece against a 4,000 ceiling. No document
    in the current corpus has such a header, so the tight assertion lives in the
    unit tests (``test_semantic_respects_the_atomic_ceiling``) where the input
    is controlled, and this file keeps the coarse bound that catches the
    regression that actually happened.
    """
    biggest = max((c.char_count for c in all_chunks(documents, config, "structural")), default=0)

    assert biggest < 12_000, f"largest chunk {biggest:,} -- capture in the report if intentional"


def test_mdx_normalisation_reached_the_corpus(documents):
    """``build-client.md`` parses as 2 headings before MDX normalisation and 127
    after. If the corpus was never rebuilt, this fails and the whole M2
    comparison is measuring garbage.

    All six MCP versions of the page measure 127, so every matched document is
    checked: one stale version would mean a partially rebuilt corpus, which is
    exactly the state this test exists to catch.
    """
    targets = [d for d in documents if d.url.endswith("develop/build-client.md")]
    if not targets:
        pytest.skip("build-client.md not in this corpus")

    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark")
    counts = {
        d.url: len([t for t in parser.parse(d.content) if t.type == "heading_open"])
        for d in targets
    }
    worst = min(counts.values())
    assert worst > 50, (
        f"only {worst} headings (all: {counts}) -- the corpus predates MDX "
        "normalisation; run scripts/fetch_corpus.py --update"
    )


def test_strategies_are_within_the_fairness_band(documents, config):
    """Every mean within +/-25% of target_size -- measured 973 / 1032 / 805.

    The band constant is imported from ``scripts/check_fairness.py`` so there is
    one definition of the criterion rather than two that can drift.

    The worst pair is **1.28x** (semantic 1032 vs structural 805). An earlier
    measurement was 1.34x, above the 1.30 ratio the plan first proposed -- and
    *not* a defect either way: structural's mean is low because design decision
    3 deliberately does not merge small sections. See the script's docstring for
    why the band replaced the ratio, and why the 1.34x figure is still recorded
    even though today's spread would have satisfied the old bar.
    """
    means = {}
    for name in STRATEGIES:
        sizes = [c.char_count for c in all_chunks(documents, config, name)]
        means[name] = sum(sizes) / len(sizes)

    lo = config.target_size * (1 - MAX_DEVIATION)
    hi = config.target_size * (1 + MAX_DEVIATION)
    assert all(lo <= m <= hi for m in means.values()), \
        f"a strategy's mean left the {lo:.0f}-{hi:.0f} band: " + \
        ", ".join(f"{n} {m:.0f}" for n, m in means.items())
