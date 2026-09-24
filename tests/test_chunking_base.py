"""Shared chunking primitives -- the fairness linchpin.

``accumulate_paragraphs`` is the cutting primitive shared by ``semantic`` and
oversized ``structural`` sections, so its contract (never cut a paragraph,
never lose a character) is pinned here once instead of per strategy.
``SizeStats`` is what the fairness report (design spec 6.3) publishes, and
``Chunker`` is the structural check the strategy implementations must satisfy.
"""

from docsentry.chunking.base import Chunker, SizeStats, accumulate_paragraphs


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
