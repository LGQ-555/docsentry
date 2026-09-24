"""The fairness report's CLI surface -- design spec 6.3.

The point of these tests is the *seam*: each chunker has its own size test, and
every one of them can be green while the three strategies have drifted apart
from each other. M1 shipped a bug through exactly that gap (three tasks each
green, the combination aborted the run), so the relationship gets its own
executable artefact and that artefact gets a test that runs it.

**The fixtures are sized, not arbitrary.** The band is a corpus-level criterion;
on a two-section corpus it is meaningless noise. The plan's original fixture
(one document, two 3,000-character sections) makes ``structural`` emit two
3,000-character chunks against ``fixed``'s 927 -- means 3.2x apart, so the gate
fires and the plan's own ``exit_code == 0`` assertion is unreachable. That is
the gate working correctly on input it was never meant for. These fixtures
mirror the real corpus instead (many documents, many moderate sections --
10 x 8 x 900 characters on the 2026-09-24 corpus's own scale), which is what
makes the band assertion below a real end-to-end check rather than a rubber
stamp. A deliberately skewed corpus is checked separately, and that one *must*
exit non-zero.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from typer.testing import CliRunner

import scripts.check_fairness as check_fairness
from scripts.check_fairness import app

runner = CliRunner()


def row_for(stdout: str, strategy: str) -> list[str]:
    """One strategy's table row, split into cells (see the printed header)."""
    line = next(line for line in stdout.splitlines() if line.startswith(strategy))
    return line.split()


def write_corpus(tmp_path, documents: list[str]):
    """One ``Document`` per element of ``documents``, as JSONL."""
    corpus = tmp_path / "corpus.jsonl"
    lines = []
    for index, content in enumerate(documents):
        lines.append(json.dumps({
            "doc_id": f"d{index}", "source": "s", "kind": "llms_txt", "version": "v",
            "url": f"https://example.test/{index}", "title": "T", "path": "p",
            "content": content,
            "content_hash": "h", "origin_format": "md",
            "fetched_at": datetime(2026, 9, 24, tzinfo=timezone.utc).isoformat(),
            "indexed_at": None,
        }))
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return corpus


def realistic_documents(*, body: int = 900, sections: int = 8, count: int = 10) -> list[str]:
    """A miniature of the real corpus: many sections, each near ``target_size``.

    Uniformity is the point -- every strategy should converge on roughly one
    section per chunk, so the band is satisfied *because the corpus is
    well-behaved*, not because the gate is lenient.
    """
    return [
        "# Top\n\n" + "\n\n".join(f"## Section {d}-{s}\n\n" + "x" * body for s in range(sections)) + "\n"
        for d in range(count)
    ]


def write_config(tmp_path, target_size: int, **extra):
    config = tmp_path / "chunking.yaml"
    settings = {"target_size": target_size, "overlap": target_size // 5, **extra}
    config.write_text("\n".join(f"{k}: {v}" for k, v in settings.items()), encoding="utf-8")
    return config


def test_report_shape(tmp_path):
    """The report names all three strategies and publishes the five stats.

    ``total_chars`` is asserted by name rather than a value: it is the column
    that exposes the overlap difference, and a report that dropped it would
    still look complete. ``dropped`` is design decision 3's published count and
    is asserted by name here, by *value* in
    ``test_dropped_chunks_are_published_not_just_dropped``.
    """
    corpus = write_corpus(tmp_path, realistic_documents())

    result = runner.invoke(app, ["--corpus", str(corpus)])

    assert result.exit_code == 0, result.output
    for name in ("fixed", "semantic", "structural"):
        assert name in result.stdout
    for column in ("chunks", "dropped", "mean", "median", "total_chars", "coverage"):
        assert column in result.stdout
    assert "FAIR" in result.stdout
    assert "disclosed, not a gate" in result.stdout


def test_dropped_chunks_are_published_not_just_dropped(tmp_path):
    """Design decision 3 ("丢弃数进报告，不静默", main spec 6.3.3 step 8): every
    strategy drops chunks with no retrievable content in them, and the report
    publishes how many.

    The wiring is the thing under test, not the drop itself -- the strategies
    counted drops and the count reached no reader, which is the silent
    degradation the rule exists to prevent, one level up. A strategy that drops
    nothing reports ``0`` rather than leaving the cell empty: "counted and
    zero" and "never counted" must not look the same in the report.
    """
    noisy = '# A\n\nReal content.\n\n## Stub\n\n<div id="enable-section-numbers" />\n'
    corpus = write_corpus(tmp_path, realistic_documents() + [noisy])

    result = runner.invoke(app, ["--corpus", str(corpus)])

    assert result.exit_code == 0, result.output
    assert row_for(result.stdout, "structural")[2] == "1", \
        "the tag-only section must be counted in the report"
    assert row_for(result.stdout, "fixed")[2] == "0"
    assert row_for(result.stdout, "semantic")[2] == "0"


def test_a_strategy_that_produces_nothing_fails_the_gate(tmp_path, monkeypatch):
    """The one failure class this artefact most needs to catch: a strategy
    silently degrading to nothing.

    The gate used to compute its means with ``if s.mean``, which *excluded* a
    zero-chunk strategy from the comparison -- so a chunker returning ``[]`` for
    every document printed FAIR and exited 0. Reported that way, "this strategy
    produced nothing" and "this strategy is fine" are the same output, which is
    the definition of failing silently. It is now a named, non-zero failure.
    """
    corpus = write_corpus(tmp_path, realistic_documents())

    class EmptyChunker:
        """Stands in for the strategy that degrades to nothing -- the shape of
        a real breakage (a bad parse path, a filter that eats everything), not a
        hypothetical one."""

        name = "structural"
        last_dropped = 0

        def __init__(self, config):
            pass

        def chunk(self, doc):
            return []

    monkeypatch.setitem(check_fairness.STRATEGIES, "structural", EmptyChunker)

    result = runner.invoke(app, ["--corpus", str(corpus)])

    assert result.exit_code == 1, result.output
    assert "no usable chunks produced by: structural" in result.stdout, \
        "the failure must name the strategy that produced nothing"
    assert "FAIR" not in result.stdout.replace("UNFAIR", ""), \
        "a zero-chunk strategy must never be reported as FAIR"


def test_config_option_is_reachable(tmp_path):
    """``--config`` is the option string callers use; a parameter named
    ``chunking_config`` must not silently become ``--chunking-config``, or
    every documented invocation would fail with "no such option".

    Asserted through the *band*, which is derived from ``target_size``: the
    default config would print ``750-1250``, so ``375-625`` can only appear if
    the file was actually read.
    """
    corpus = write_corpus(tmp_path, realistic_documents(body=450, sections=8, count=10))
    config = write_config(tmp_path, target_size=500)

    result = runner.invoke(app, ["--corpus", str(corpus), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "375-625" in result.stdout


def test_unfair_means_exit_nonzero(tmp_path):
    """The band is a gate, not decoration.

    One document whose entire body is a single unbreakable paragraph: with the
    ceiling raised out of the way, ``structural`` emits it whole while ``fixed``
    still cuts it into ``target_size`` windows. The means are far enough apart
    to leave the band, which must fail the run rather than print a warning
    nobody reads.
    """
    corpus = write_corpus(tmp_path, ["# A\n\n" + "x" * 30_000 + "\n"])
    config = write_config(tmp_path, target_size=2000, max_atomic_size=100_000)

    result = runner.invoke(app, ["--corpus", str(corpus), "--config", str(config)])

    assert result.exit_code == 1, result.output
    assert "UNFAIR" in result.stdout


def test_limit_truncates_the_document_set(tmp_path):
    """``--limit`` is how a caller narrows the run; it must be reported, or a
    partial run reads as a full one."""
    corpus = write_corpus(tmp_path, realistic_documents(count=4))

    result = runner.invoke(app, ["--corpus", str(corpus), "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "docs 2" in result.stdout
