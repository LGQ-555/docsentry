"""Shared chunking primitives -- the fairness linchpin.

``accumulate_paragraphs`` is the cutting primitive shared by ``semantic`` and
oversized ``structural`` sections, so its contract (never cut a paragraph,
never lose a character) is pinned here once instead of per strategy.
``SizeStats`` is what the fairness report (design spec 6.3) publishes, and
``Chunker`` is the structural check the strategy implementations must satisfy.

Since Task 12b, this module also hosts decision 2's forced-degradation
helpers (``segment_blocks`` / ``block_kind`` / ``cut_atomic``), lifted out of
``structural.py`` because ``semantic`` now consumes them too -- the ceiling
is a system rule, not a structural feature.
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import (
    Chunker,
    SizeStats,
    accumulate_paragraphs,
    cut_atomic,
    effective_target,
    is_noise,
    segment_blocks,
)
from docsentry.chunking.semantic import SemanticChunker
from docsentry.chunking.structural import StructuralChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind


def test_accumulate_respects_the_target():
    text = "a" * 400 + "\n\n" + "b" * 400 + "\n\n" + "c" * 400
    pieces = accumulate_paragraphs(text, target=1000)

    assert len(pieces) == 2
    assert pieces[0].startswith("a")
    assert pieces[1].startswith("c")


def test_accumulate_never_splits_a_paragraph():
    """A paragraph longer than the target is emitted whole -- it is one unit."""
    text = "x" * 5000
    assert accumulate_paragraphs(text, target=1000) == [text]


def test_accumulate_keeps_short_text_whole():
    assert accumulate_paragraphs("short", target=1000) == ["short"]


def test_accumulate_round_trips_blank_line_runs():
    """Joining the pieces with the separator reproduces the text exactly, even
    when a blank-line run splits into empty paragraphs."""
    text = "a\n\n\n\nb"
    pieces = accumulate_paragraphs(text, target=5)
    assert "\n\n".join(pieces) == text


def test_size_stats_reports_what_the_fairness_check_needs():
    stats = SizeStats.from_sizes([100, 200, 300])
    assert stats.count == 3
    assert stats.mean == 200
    assert stats.median == 200
    assert stats.total_chars == 600


def test_size_stats_empty_input_is_zeroed():
    """A zero-chunk strategy must fail the fairness gate, and it can only be
    reported if this returns zeros instead of raising -- the script reads
    ``stats.mean`` to detect the case (using ``if s.mean`` to *exclude* such a
    strategy was the bug; see ``scripts/check_fairness.py``)."""
    stats = SizeStats.from_sizes([])
    assert (stats.count, stats.mean, stats.median, stats.total_chars) == (0, 0.0, 0.0, 0)


def test_a_conforming_class_satisfies_the_protocol():
    """Tasks 6-8's strategies are dispatched with structural ``isinstance``
    checks; a class-level ``name``, a class-level ``last_dropped`` and a
    ``chunk`` method is exactly the shape they ship, and ``runtime_checkable``
    checks member *presence*, not signatures. ``last_dropped`` is part of the
    contract, not an extra on one class: the fairness report reads it to
    publish design decision 3's drop count."""
    class FakeChunker:
        name = "fake"
        last_dropped = 0

        def chunk(self, doc):
            return []

    assert isinstance(FakeChunker(), Chunker)


def test_a_class_without_chunk_does_not_satisfy_it():
    class NoChunk:
        name = "fake"

    assert not isinstance(NoChunk(), Chunker)


def test_is_noise_strips_tags_before_judging():
    """The noise bar is deliberately narrow (design spec 6.3.3 step 8, M2
    decision 3): only "empty after stripping HTML tags" counts. Corpus
    sampling found sub-200-character sections are mostly precise API
    fragments developers query for, and a heading-only body is unusual but
    retrievable -- neither is noise."""
    assert is_noise('<div id="x" />')
    assert is_noise("   \n\n  ")
    assert not is_noise("Real content.")
    assert not is_noise("# heading only")


# --- Task 12b: decision 2's forced-degradation helpers, now shared ---


def test_segment_blocks_splits_at_structural_boundaries():
    """The blocks are the unit the chunkers pack and never cut inside: blank
    lines, fence lines (prose glued to a closing fence must not ride into the
    code block) and pipe-line runs (a glued paragraph must not become a table
    row)."""
    text = (
        "Intro paragraph.\n"
        "\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "Glued prose after the fence.\n"
        "| a | b |\n"
        "| c | d |\n"
        "Prose after the table.\n"
    )
    blocks = segment_blocks(text)

    assert [kind for kind, _ in blocks] == ["prose", "code", "prose", "table", "prose"]
    # Blocks are a partition: joining them reproduces the text minus the blank
    # separators -- nothing lost, nothing moved.
    assert "".join(block for _, block in blocks) == text.replace("\n\n", "\n")


def test_cut_atomic_respects_the_ceiling_for_every_kind():
    """The lifted helper is what guarantees forced cuts stay embeddable.
    Every kind must return pieces that never exceed ``max_atomic_size``, and a
    table cut repeats the header row + delimiter row so each piece stays
    readable on its own."""
    cfg = ChunkingConfig(target_size=1000, max_atomic_size=1500)
    table = ("| key | value |\n| --- | --- |\n"
             + "".join(f"| r{i} | v{i} |\n" for i in range(300)))
    code = ("```python\n"
            + "\n".join(f"def f{i}():\n    return {i}" for i in range(300))
            + "\n```\n")
    prose = "word " * 3000

    for kind, block in (("table", table), ("code", code), ("prose", prose)):
        pieces = cut_atomic(kind, block, cfg)
        assert pieces, kind
        assert all(len(piece) <= 1500 for piece in pieces), (kind, max(map(len, pieces)))

    for piece in cut_atomic("table", table, cfg):
        assert piece.startswith("| key | value |\n| --- | --- |"), \
            "a piece of a table without its header is unreadable"


def test_a_header_wider_than_the_ceiling_is_not_repeated():
    """Repeating the header keeps the ceiling only while
    ``header + budget <= ceiling``. Measured 2026-09-24: the widest header on
    the corpus is 2,028 chars against a 3,000 allowance, so this guard is a
    no-op on today's data -- it exists so a future corpus cannot silently
    produce pieces that exceed the limit the function exists to enforce."""
    cfg = ChunkingConfig(target_size=1000, max_atomic_size=1500)
    header = "| " + "c" * 8000 + " |\n"
    delimiter = "|---|---|\n"
    block = header + delimiter + "".join(f"| row{i} |\n" for i in range(50))

    pieces = cut_atomic("table", block, cfg)

    assert pieces
    assert all(len(piece) <= cfg.max_atomic_size for piece in pieces), \
        max(map(len, pieces))


# --- M2 fix pass: the ceiling binds the packing target, system-wide ---


def test_effective_target_caps_the_granularity_at_the_ceiling():
    """The rule had two implementations and they disagreed: ``semantic`` packed
    to ``min(target_size, max_atomic_size)``, ``structural`` to the raw
    ``target_size``. Under the config below that difference was measured as 272
    ``structural`` chunks over the ceiling, the largest 7,989, while
    ``semantic`` respected it. One rule, one function.

    The config is built with ``model_construct`` because that combination is
    now **rejected at load** -- ``ChunkingConfig`` enforces ``target_size <=
    max_atomic_size`` (see ``tests/test_config.py``), because one config that
    lets ``fixed`` emit 8,000-character windows while the other two cap at
    4,000 is three strategies measuring three different things. What remains
    here is the second line of defence: the packers call ``effective_target``,
    so a config object that reached them without passing validation is still
    capped rather than silently over-ceiling.
    """
    incoherent = ChunkingConfig.model_construct(target_size=8000, max_atomic_size=4000)
    assert effective_target(incoherent) == 4000
    # The identity under every config the loader accepts -- which is why no
    # recorded measurement moves now that the load-time guard exists.
    assert effective_target(ChunkingConfig()) == 1000


@pytest.mark.parametrize("chunker_cls", [SemanticChunker, StructuralChunker])
def test_every_packer_respects_the_ceiling_under_a_target_above_it(chunker_cls):
    """Both chunkers that pack must cap their packing target, not just their
    atomic units -- ``structural`` did not until the M2 fix pass, and emitted
    7,989-character chunks under exactly this config.

    Defence in depth, and labelled as such: the config is ``model_construct``ed
    because ``ChunkingConfig`` now rejects it. The assertion stays because it
    pins the packers' own contract -- "whatever config object I am handed, I
    never emit a chunk over the ceiling" -- independently of who built that
    object, which is the invariant the M2 acceptance test relies on.

    Non-vacuity: the fixture paragraphs are large enough that a correct packer
    still lands well above the *shipped* target (1,000), so a chunker that
    passed this by emitting tiny chunks would fail the second assertion.
    """
    config = ChunkingConfig.model_construct(target_size=8000, max_atomic_size=4000)
    doc = Document(
        doc_id="d", source="s", kind=SourceKind.LLMS_TXT, version="v",
        url="u", title="t", path="p",
        content="# A\n\n" + "\n\n".join("p" * 1500 for _ in range(12)) + "\n",
        content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    chunks = chunker_cls(config).chunk(doc)
    biggest = max(c.char_count for c in chunks)

    assert biggest <= config.max_atomic_size, \
        f"{chunker_cls.name} emitted a {biggest:,}-character chunk " \
        f"against a {config.max_atomic_size:,} ceiling"
    assert biggest > ChunkingConfig().target_size, \
        "the fixture must actually exercise the larger target, not the shipped one"
