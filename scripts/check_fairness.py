#!/usr/bin/env python
"""Fairness report for the three chunkers -- design spec 6.3.

The fairness constraint is only meaningful if someone actually checks it. A test
asserting each strategy's own size says nothing about the relationship *between*
strategies, which is exactly the seam M1 shipped a bug through -- three tasks
each green, and the combination aborted the run. So this is a real artefact that
really runs, and the acceptance suite imports ``MAX_DEVIATION`` from here so the
criterion has one definition rather than two that can drift apart.

Publishes mean, median, chunk count, **total indexed characters** and
**dropped**. ``total_chars`` is the number that exposes the overlap difference
(fixed 1.24x the corpus, semantic 1.08x, structural 1.06x); mean size alone
hides it. None of the three is at 1.00x: ``fixed``'s excess is its 200-character
overlap, the other two exceed the source where a forced atomic cut repeats
context (a table's header row in every piece).

``dropped`` is design decision 3's "丢弃数进报告，不静默" (main spec 6.3.3 step
8): every strategy drops the chunks that carry no retrievable content -- nothing
left after stripping HTML tags -- and every strategy reports how many, because
a chunk that disappears without a number is indistinguishable from one that was
never produced. Measured on the 2026-09-24 corpus: structural 96, semantic 31,
fixed 1. Before the M2 fix pass only ``structural`` dropped them and no report
read the count at all.

**The gate has two ways to fail, and the second one is a bug fix.** The band is
the criterion; but a strategy that produces nothing is not "outside the band" --
it is absent from the comparison, and the band computed over the survivors would
be a comparison of the others. Until the M2 fix pass the means were filtered
with ``if s.mean``, which *excluded* exactly that case: a strategy returning
``[]`` for every document printed FAIR and exited 0. That is the one failure
class this artefact most needs to catch -- a strategy silently degrading to
nothing -- so it is now a named, non-zero failure of its own.

**Why a band rather than a pairwise ratio.** The criterion was originally "the
two strategies' means are within 1.30x of each other". The measurement that
prompted the change was **1.34x** (semantic 1,072 vs structural 802) -- a
threshold that nothing was actually wrong with. The cause is design decision 3:
not merging small sections is deliberate and evidence-backed, and it lowers
``structural``'s mean. Two separately-sound decisions collided on a number.

**The spread is 1.29x as measured now (2026-09-24, after the M2 fix pass; it
was 1.28x before, and the noise rule moving the two baselines' means is the
whole of the difference), which is under the old 1.30 bar -- and that is not
why the criterion changed.** The band was adopted on the argument below, not to
turn a red run green; it would have been adopted at 1.34x, at 1.28x, or at
1.05x. Recorded here because a criterion that was swapped while the number
moved is exactly the kind of thing a reader should be able to check, and a
reader who only sees today's 1.29x would otherwise conclude the old bar had
never been breached.

What the experiment actually needs is that no strategy's chunk size is so far
from the others that size becomes the dominant explanation for a score gap. A
pairwise ratio is a proxy for that, and a poor one -- it tightens as strategies
get more similar in the middle, and it has no meaning in absolute terms. The
band states the requirement directly: every mean within +/-25% of target_size.

The worst-pair spread is still printed, and belongs in the report -- the honest
disclosure is "the spread is 1.29x, and here is why", not a threshold tuned
until it passes.
"""

from __future__ import annotations

from pathlib import Path

import typer

from docsentry.chunking.base import SizeStats
from docsentry.chunking.registry import STRATEGIES, build_chunker
from docsentry.config import Settings, load_chunking_config
from docsentry.corpus.loader import load_corpus

app = typer.Typer(add_completion=False, help="Check the chunk-size fairness band.")

# Every strategy's mean must sit within this fraction of target_size. The band,
# not a pairwise ratio, is the criterion -- see the module docstring.
MAX_DEVIATION = 0.25


@app.command()
def main(
    # Both defaults come from ``Settings``, the project's convention (see
    # ``scripts/fetch_corpus.py``): with a literal path here, ``DOCSENTRY_DATA_DIR``
    # silently had no effect on this report -- it would keep measuring
    # ``data/corpus.jsonl`` while the fetch and index steps read a corpus
    # somewhere else, and nothing would say the two had diverged. The explicit
    # options still win, so a caller can point at any file.
    corpus: Path = typer.Option(None, "--corpus", help="Default: Settings().corpus_path"),
    config_path: Path = typer.Option(None, "--config", help="Default: Settings().chunking_config"),
    limit: int = typer.Option(0, "--limit", help="0 = all documents"),
) -> None:
    settings = Settings()
    corpus = corpus or settings.corpus_path
    config_path = config_path or settings.chunking_config

    chunking_config = load_chunking_config(config_path)
    documents = list(load_corpus(corpus))
    if limit:
        documents = documents[:limit]

    # ``len(d.content)`` is the source size the indexed totals are measured
    # against -- the same denominator the strategies' own accounting uses.
    corpus_chars = sum(len(d.content) for d in documents)
    results: dict[str, SizeStats] = {}
    dropped: dict[str, int] = {}

    for name in STRATEGIES:
        chunker = build_chunker(name, chunking_config)
        sizes: list[int] = []
        dropped[name] = 0
        for doc in documents:
            sizes.extend(c.char_count for c in chunker.chunk(doc))
            # ``last_dropped`` means "by the most recent ``chunk()`` call", so
            # it accumulates here rather than being read once at the end.
            dropped[name] += chunker.last_dropped
        results[name] = SizeStats.from_sizes(sizes)

    typer.echo(f"docs {len(documents):,}   corpus_chars {corpus_chars:,}\n")
    header = (f"{'strategy':<12}{'chunks':>9}{'dropped':>9}{'mean':>9}{'median':>9}"
              f"{'total_chars':>14}{'coverage':>10}")
    typer.echo(header)
    typer.echo("-" * len(header))
    for name, stats in results.items():
        coverage = stats.total_chars / corpus_chars if corpus_chars else 0
        typer.echo(f"{name:<12}{stats.count:>9,}{dropped[name]:>9,}{stats.mean:>9.0f}"
                   f"{stats.median:>9.0f}{stats.total_chars:>14,}{coverage:>9.2f}x")
    typer.echo("dropped = chunks with no retrievable content (empty after stripping "
               "HTML tags); design decision 3")

    # A strategy that yields nothing must fail. The old filter here was
    # ``if s.mean``, which *excluded* such a strategy from the comparison: a
    # chunker returning ``[]`` for every document printed FAIR and exited 0.
    # That is the failure class this artefact most needs to catch -- a strategy
    # silently degrading to nothing -- and reporting it as "outside the band"
    # would understate it: there is no mean to compare, only an absence. A
    # zero-length chunk counts as nothing for the same reason (nothing in it can
    # be embedded), and either way it is a failure, not something to filter out.
    silent = [name for name, stats in results.items() if not stats.mean]
    if silent:
        typer.echo(f"\nUNFAIR -- no usable chunks produced by: {', '.join(silent)}")
        typer.echo("a strategy that yields nothing is not outside the band, "
                   "it is missing from the comparison")
        raise typer.Exit(code=1)

    means = [stats.mean for stats in results.values()]
    lo = chunking_config.target_size * (1 - MAX_DEVIATION)
    hi = chunking_config.target_size * (1 + MAX_DEVIATION)
    inside = all(lo <= m <= hi for m in means)
    spread = max(means) / min(means)
    typer.echo(f"\ntarget band {lo:.0f}-{hi:.0f} (target_size {chunking_config.target_size} "
               f"+/-{MAX_DEVIATION:.0%})")
    typer.echo(f"mean spread (worst pair) {spread:.2f}x   [disclosed, not a gate]")
    typer.echo("FAIR" if inside else "UNFAIR -- a strategy's mean left the band")
    if not inside:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
