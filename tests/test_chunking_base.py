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

from docsentry.chunking.base import (
    Chunker,
    SizeStats,
    accumulate_paragraphs,
    cut_atomic,
    segment_blocks,
)
from docsentry.config import ChunkingConfig


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
    """The fairness script excludes zero-chunk strategies via ``if s.mean`` --
    that guard only works if empty input yields 0.0, not an exception."""
    stats = SizeStats.from_sizes([])
    assert (stats.count, stats.mean, stats.median, stats.total_chars) == (0, 0.0, 0.0, 0)


def test_a_conforming_class_satisfies_the_protocol():
    """Tasks 6-8's strategies are dispatched with structural ``isinstance``
    checks; a class-level ``name`` plus a ``chunk`` method is exactly the
    shape they ship, and ``runtime_checkable`` checks member *presence*, not
    signatures."""
    class FakeChunker:
        name = "fake"

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
    from docsentry.chunking.base import is_noise

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
