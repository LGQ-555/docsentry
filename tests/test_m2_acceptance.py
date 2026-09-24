"""M2 acceptance against the real corpus.

Marked ``corpus`` and excluded by default. Assertions use *lower bounds* and
*ratios*, never exact totals: the corpus moves underneath us (LangChain's index
restructured 2026-09-20 -> 09-22, 369 -> 539 documents).

Measured on the 2026-09-24 corpus (774 documents, 14,049,846 characters);
``uv run scripts/check_fairness.py`` reproduces this table:

    strategy     chunks  dropped    mean  median  total_chars  coverage
    fixed        17,940        1     974    1000   17,465,281     1.24x
    semantic     14,651       31    1034     911   15,154,449     1.08x
    structural   18,442       96     805     642   14,840,156     1.06x

(``dropped`` is design decision 3's noise count; the two baselines' counts and
means moved from 17,941/973 and 14,682/1032 when the noise rule became a system
rule, which is the whole of the difference between those figures and the ones
recorded before the M2 fix pass.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docsentry.chunking.base import is_noise
from docsentry.chunking.registry import STRATEGIES, build_chunker
from docsentry.config import Settings, load_chunking_config
from docsentry.corpus.loader import load_corpus
from scripts.check_fairness import MAX_DEVIATION

pytestmark = pytest.mark.corpus

# The *configured* corpus, not a literal path -- the same ``Settings().corpus_path``
# the fairness report (and the fetch/index steps) read. A literal here would
# quietly measure one corpus while the artefact measured another whenever
# ``DOCSENTRY_DATA_DIR`` points somewhere else, and the divergence would be
# invisible, which is the failure mode this whole milestone is about. The skip
# stays predictable: it fires exactly when the configured corpus does not exist,
# which is the same condition as before.
CORPUS = Settings().corpus_path


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


def test_every_strategy_respects_the_atomic_ceiling(documents, config):
    """The ceiling is a system rule (M2 design decision 2, main spec 6.3 step 6),
    so it is asserted here as the invariant it is -- ``max(char_count) <=
    max_atomic_size`` -- for **every** strategy, and as a companion that no
    strategy indexes a chunk with nothing retrievable in it.

    Why an inequality rather than a pinned number: the ceiling is a *bound*, and
    where it is reached is a property of the corpus, not of the rule. Measured
    today, ``semantic`` and ``structural`` reach it exactly (4,000 -- every
    maximum is a forced atomic cut at the ceiling) while ``fixed`` sits at 1,000,
    its window. Asserting ``== 4_000`` for all three would be false, asserting
    it for the two would fail the day the corpus's largest atomic unit shrinks,
    and neither would say anything about the rule.

    This reads ``configs/chunking.yaml``, so it is also the guard on *editing*
    that file: under ``target_size=8000, max_atomic_size=4000`` ``structural``
    packed to the raw target and emitted 7,989-character chunks -- measured
    against ``semantic``'s 4,000 on the same corpus, which is how the two
    consumers of the ceiling were found to have different contracts. That
    config can no longer be edited in at all: ``ChunkingConfig`` rejects
    ``target_size > max_atomic_size`` at load, which is the stronger version of
    this guard (it fires before 774 documents are chunked, not after). A
    non-default config is not something this suite should pay 774 documents to
    re-measure, so the unit-level assertion lives in
    ``tests/test_chunking_base.py`` (``test_every_packer_respects_the_ceiling_
    under_a_target_above_it``), where the config is a parameter.

    The previous version of this test used a loose ``< 12_000`` bar and a false
    rationale: it said ``cut_atomic`` cannot guarantee the ceiling because its
    table branch does not check the header against the budget. That was true
    before the ``header_fits`` guard landed in the same commit as the docstring,
    and false after -- ``cut_atomic`` drops the repeated header rather than
    exceed the ceiling, and ``tests/test_chunking_base.py``
    (``test_a_header_wider_than_the_ceiling_is_not_repeated``) pins it. A loose
    bar justified by a bug that is already fixed is how a real regression stays
    inside the bar and unreported.
    """
    for name in STRATEGIES:
        chunks = all_chunks(documents, config, name)
        biggest = max((c.char_count for c in chunks), default=0)
        assert biggest <= config.max_atomic_size, \
            f"{name} emitted a {biggest:,}-character chunk against a {config.max_atomic_size:,} ceiling"
        # An unembeddable chunk in the index is the same class of silent failure
        # the ceiling exists to prevent, one step earlier: nothing in it can be
        # embedded, and nothing downstream can tell it apart from a real chunk.
        noise = [c for c in chunks if is_noise(c.text)]
        assert not noise, f"{name} indexed {len(noise)} chunk(s) with no retrievable content"


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
    """Every mean within +/-25% of target_size -- measured 974 / 1034 / 805.

    The band constant is imported from ``scripts/check_fairness.py`` so there is
    one definition of the criterion rather than two that can drift.

    The worst pair is **1.29x** (semantic 1034 vs structural 805), up from 1.28x
    only because the noise rule (design decision 3, applied to all three
    strategies since the M2 fix pass) removed 32 chunks from the two baselines,
    moving their means. An earlier measurement was 1.34x, above the 1.30 ratio
    the plan first proposed -- and *not* a defect either way: structural's mean
    is low because design decision 3 deliberately does not merge small sections.
    See the script's docstring for why the band replaced the ratio, and why the
    1.34x figure is still recorded even though today's spread would have
    satisfied the old bar.
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
