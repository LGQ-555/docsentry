"""``StructuralChunker`` contract tests -- design spec 6.3.3, M2 design decision 1.

Two of these pin defects that only show up when the implementation is *run*,
not when it is read:

* ``test_document_order_is_preserved`` -- emitting a section's body when the
  section is *popped* reverses the document (C, B, A); the body must be flushed
  the moment a heading opens inside or beside it.
* ``test_heading_text_is_not_part_of_the_body`` -- the token stream cannot be
  accumulated from directly: ``heading_open`` and the ``inline`` after it share
  one token map, and ``paragraph_open`` / ``inline`` / ``paragraph_close``
  share theirs, so token-by-token accumulation appends each line once per
  covering token and files the heading line itself into the body.

And one pins the milestone's measured bug: flush-on-close (not "leaf
sections") is what brings the 18% back -- emitting only leaf bodies drops
2,618,528 characters of the real corpus, including all 80,448 of
``build-client.md``.

The Task 10 tests pin decision 2's hard ceiling (M2 design 2, main spec
6.3.3 step 6): atomic units are never cut below ``max_atomic_size`` and must
be cut above it, with ``split_atomic=True`` on every forced-cut piece. Four
of them pin defects that only show up when the plan's code is *run*:

* ``test_forced_code_pieces_pack_to_the_budget_not_per_definition`` -- the
  plan's code cuts at *every* top-level ``def``, so a 300-definition block
  becomes 300 pieces of ~20 characters; ``max_code_size`` is a budget, not a
  per-definition quota.
* ``test_prose_glued_after_a_closing_fence_is_not_cut_as_code`` and
  ``test_prose_glued_after_a_table_carries_no_header`` -- a block glued to
  its neighbour (no blank line) rides into ``_cut_atomic``, which would cut
  prose as code / repeat the table header over prose.
* ``test_oversized_unbroken_prose_run_is_hard_cut_and_flagged`` -- measured
  on the corpus, 176 prose runs exceed 4,000 characters (the 106,285-char
  one included); uncut they are the silent-failure chunks decision 2 exists
  to eliminate.
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import Chunker
from docsentry.chunking.structural import StructuralChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind


def make_doc(content: str) -> Document:
    return Document(
        doc_id="d", source="mcp", kind=SourceKind.LLMS_TXT, version="2026-07-28",
        url="https://example.com/a.md", title="A", path="a.md",
        content=content, content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


@pytest.fixture
def chunker():
    return StructuralChunker(ChunkingConfig(target_size=1000))


def test_breadcrumb_reflects_the_heading_stack(chunker):
    doc = make_doc("# Guide\n\n## Setup\n\n### Prereqs\n\nInstall it.\n")
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].breadcrumb == ["Guide", "Setup", "Prereqs"]
    assert "Install it." in chunks[0].text


def test_parent_section_body_is_not_dropped(chunker):
    """The 18% bug. Text under a heading that later gains a child belongs to
    that heading -- not to nothing. Measured on the real corpus, emitting only
    leaf sections dropped 2,618,528 characters."""
    doc = make_doc(
        "# Build a client\n"
        "\n"
        "This intro sits under the H1 but before the first H2.\n"
        "\n"
        "## Next steps\n"
        "\n"
        "Done.\n"
    )
    chunks = chunker.chunk(doc)

    assert any("This intro sits under the H1" in c.text for c in chunks), \
        "the parent section body vanished"
    assert any(c.breadcrumb == ["Build a client"] for c in chunks if "intro" in c.text)
    assert any(c.breadcrumb == ["Build a client", "Next steps"] for c in chunks)


def test_flush_happens_before_the_stack_pops(chunker):
    """Ordering matters: the accumulated text must be attributed to the section
    it was written under, not the one that closed it."""
    doc = make_doc("# A\n\nbody of A\n\n## B\n\nbody of B\n")
    chunks = {tuple(c.breadcrumb): c for c in chunker.chunk(doc)}

    assert "body of A" in chunks[("A",)].text
    assert "body of A" not in chunks[("A", "B")].text


def test_empty_sections_produce_no_chunk(chunker):
    doc = make_doc("# A\n\n## B\n\nreal content\n")
    chunks = chunker.chunk(doc)

    assert all(c.text.strip() for c in chunks)
    assert len(chunks) == 1


def test_document_order_is_preserved(chunker):
    """Emitting a section's body when it is *popped* reverses the document
    (C, B, A). Both a sibling and a child heading must flush the section above
    them the moment they arrive."""
    doc = make_doc("# A\n\nbody of A\n\n## B\n\nbody of B\n\n### C\n\nbody of C\n")
    chunks = chunker.chunk(doc)

    assert [c.breadcrumb for c in chunks] == [["A"], ["A", "B"], ["A", "B", "C"]]
    assert "body of A" in chunks[0].text
    assert "body of B" in chunks[1].text
    assert "body of C" in chunks[2].text


def test_heading_text_is_not_part_of_the_body(chunker):
    """`heading_open` and the `inline` after it share one token map, and
    `paragraph_open`/`inline`/`paragraph_close` share theirs -- accumulating
    bodies straight from token maps appends each line once per covering token
    and puts the heading line in the body."""
    doc = make_doc("# Guide\n\n## Setup\n\nReal content.\n")
    chunks = chunker.chunk(doc)

    for chunk in chunks:
        assert not chunk.text.lstrip().startswith("#"), chunk.text[:40]
    assert "Real content." in chunks[0].text


def test_headings_the_raw_line_regex_cannot_title_keep_their_text(chunker):
    """CommonMark accepts up to three leading spaces before ``#`` and lets a
    heading open inside a list item; markdown-it emits ``heading_open`` for
    both. Measured on the real corpus: 82 of 11,571 headings fall here, and
    each would file its section under an empty breadcrumb component."""
    doc = make_doc(
        "## Setup\n\nReal content.\n\n"
        "  ## Teardown\n\nStop it.\n\n"
        "- ### Cleanup\n\nDelete it.\n"
    )
    chunks = chunker.chunk(doc)

    assert [tuple(c.breadcrumb) for c in chunks] == [
        ("Setup",), ("Teardown",), ("Teardown", "Cleanup"),
    ]
    assert all(all(part for part in c.breadcrumb) for c in chunks)
    assert "Stop it." in chunks[1].text
    assert "Delete it." in chunks[2].text


def test_structural_empty_document_yields_no_chunks(chunker):
    """Same contract as the two baselines: a zero-character chunk is
    unembeddable, and ``fixed`` / ``semantic`` both yield nothing for the same
    document."""
    assert chunker.chunk(make_doc("")) == []


def test_structural_satisfies_the_chunker_protocol():
    """Strategies are dispatched with structural ``isinstance`` checks."""
    assert isinstance(StructuralChunker(ChunkingConfig()), Chunker)


def test_oversized_section_splits_into_children_sharing_the_breadcrumb(chunker):
    """A section body over ``target_size`` is cut into pieces, but every piece
    keeps the full breadcrumb -- the retrieval assumption is "this chunk sits
    under these headings", and a piece of a big section must not lose that."""
    doc = make_doc("# Guide\n\n## Big\n\n" + "\n\n".join(["p" * 400] * 6) + "\n")
    chunks = chunker.chunk(doc)

    big = [c for c in chunks if c.breadcrumb == ["Guide", "Big"]]
    assert len(big) > 1, "an oversized section must be split"
    assert all(c.breadcrumb == ["Guide", "Big"] for c in big)


def test_kind_is_code_when_fences_dominate(chunker):
    doc = make_doc("# A\n\n```python\n" + "x = 1\n" * 100 + "```\n")
    assert chunker.chunk(doc)[0].kind == "code"


def test_kind_is_table_when_table_dominates(chunker):
    rows = "".join(f"| r{i} | v{i} |\n" for i in range(80))
    doc = make_doc("# A\n\n| k | v |\n|---|---|\n" + rows)
    assert chunker.chunk(doc)[0].kind == "table"


def test_kind_is_prose_for_plain_text(chunker):
    doc = make_doc("# A\n\nJust some prose about the system.\n")
    assert chunker.chunk(doc)[0].kind == "prose"


def test_fallback_warns_and_still_produces_chunks(chunker, monkeypatch):
    """Design spec 6.3.3: malformed Markdown degrades rather than producing
    nothing, **and records the degradation**. A document that silently loses
    its whole heading structure is indistinguishable from one that never had
    any -- the warning is the only evidence the degradation happened."""
    def boom(content: str) -> list:
        raise ValueError("synthetic parse failure")

    monkeypatch.setattr(chunker, "_sections", boom)
    with pytest.warns(RuntimeWarning, match="fell back to paragraph accumulation"):
        chunks = chunker.chunk(make_doc("# A\n\nSome content.\n"))

    assert len(chunks) == 1
    assert chunks[0].breadcrumb == ["A"]          # title fallback, not []
    assert "Some content." in chunks[0].text


# --- Task 10: the max_atomic_size hard ceiling (M2 design decision 2) ---


def test_short_code_block_is_never_cut(chunker):
    code = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(20)) + "\n```\n"
    doc = make_doc("# A\n\nIntro text.\n\n" + code)
    chunk = chunker.chunk(doc)[0]

    assert code.strip() in chunk.text
    assert chunk.split_atomic is False


def test_table_over_the_ceiling_is_split_with_repeated_header():
    """A 106,728-character table was measured on the real corpus. Left atomic it
    silently fails: the embedding truncates and the prompt cannot hold it."""
    header = "| key | value |\n| --- | --- |\n"
    rows = "".join(f"| key_{i} | value_{i} |\n" for i in range(300))
    doc = make_doc("# A\n\n" + header + rows)
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert len(chunks) > 1
    assert all(c.split_atomic for c in chunks)
    for chunk in chunks:
        assert "| key | value |" in chunk.text, "each piece must carry the header"
        assert "| --- | --- |" in chunk.text


def test_code_block_over_the_ceiling_is_split_and_flagged():
    body = "\n".join(f"def f{i}():\n    return {i}" for i in range(300))
    doc = make_doc("# A\n\n```python\n" + body + "\n```\n")
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert len(chunks) > 1
    assert all(c.split_atomic for c in chunks)


def test_forced_code_pieces_pack_to_the_budget_not_per_definition():
    """300 top-level defs must not become 300 pieces. ``max_code_size`` is a
    piece *budget*: a top-level boundary is where the cut lands when the
    budget is exceeded, not a reason to cut on every sighting -- per-def
    pieces would flood the index with 20-character chunks."""
    body = "\n".join(f"def f{i}():\n    return {i}" for i in range(300))
    doc = make_doc("# A\n\n```python\n" + body + "\n```\n")
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert len(chunks) <= 6, f"~6,300 characters over a 1,500 budget, got {len(chunks)}"
    # Every piece but the final remainder must be packed near the budget;
    # per-definition pieces would be ~20-40 characters each.
    assert all(len(c.text) > 200 for c in chunks[:-1]), "pieces must pack, not fragment"


def test_prose_glued_after_a_closing_fence_is_not_cut_as_code():
    """No blank line after the closing fence: the paragraph must not glue onto
    the code block, or ``_cut_atomic`` would cut it as code and flag it."""
    body = "\n".join(f"def f{i}():\n    return {i}" for i in range(300))
    doc = make_doc(
        "# A\n\n```python\n" + body + "\n```\n"
        "A paragraph right after the fence with no blank line.\n"
    )
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    para = [c for c in chunks if "right after the fence" in c.text]
    assert para, "the paragraph must survive"
    assert not para[0].split_atomic, "prose is not a piece of the code block"


def test_prose_glued_after_a_table_carries_no_header():
    """No blank line after the last row: the paragraph must not ride into the
    table block, or every piece would repeat the header over it."""
    header = "| key | value |\n| --- | --- |\n"
    rows = "".join(f"| key_{i} | value_{i} |\n" for i in range(200))
    doc = make_doc("# A\n\n" + header + rows + "A paragraph glued to the table.\n")
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    para = [c for c in chunks if "glued to the table" in c.text]
    assert len(para) == 1
    assert not para[0].split_atomic
    assert "| key | value |" not in para[0].text, "the header must not repeat over prose"
    assert all(c.split_atomic for c in chunks if c is not para[0])


def test_giant_line_inside_a_code_block_is_cut_mid_line():
    """Measured on the corpus: minified blobs inside unclosed-fence blocks
    hold single lines longer than the whole piece budget. Without a mid-line
    cut they sail through whole -- the same silent-failure chunk decision 2
    exists to eliminate -- and the fence opener must not become a piece by
    itself."""
    doc = make_doc("# A\n\n```text\n" + "x" * 5000 + "\n```\n")
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert len(chunks) > 1
    assert all(c.split_atomic for c in chunks)
    assert all(c.char_count <= 1500 + 12 for c in chunks)  # opener + closer slack
    assert not any(c.text.strip() == "```text" for c in chunks), "no lone-opener piece"


def test_oversized_unbroken_prose_run_is_hard_cut_and_flagged():
    """176 prose runs over ``max_atomic_size`` were measured on the corpus, the
    106,285-character one included. A run with no blank line, fence or pipe
    row has no boundary to respect, so it is hard-cut and flagged like an
    atomic unit -- uncut it would be the silent-failure chunk decision 2
    exists to eliminate."""
    doc = make_doc("# A\n\n" + "word " * 3000 + "\n")  # ~15,000 chars, one line
    small = StructuralChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert len(chunks) > 1
    assert all(c.split_atomic for c in chunks)
    assert all(c.char_count <= 1500 for c in chunks)


def test_table_between_target_and_ceiling_stays_whole_and_unflagged(chunker):
    """The design's one exception to the shared ``target_size``: an atomic unit
    under ``max_atomic_size`` is not cut even when it alone exceeds the
    target. Two ceilings -- the target is negotiable for an atomic unit, the
    hard one never is."""
    header = "| key | value |\n| --- | --- |\n"
    rows = "".join(f"| key_{i} | value_{i} |\n" for i in range(120))
    doc = make_doc("# A\n\n" + header + rows)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].split_atomic is False


def test_code_block_between_target_and_ceiling_stays_whole_and_unflagged(chunker):
    body = "\n".join(f"line_{i} = {i}" for i in range(150))
    doc = make_doc("# A\n\n```python\n" + body + "\n```\n")
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].split_atomic is False


def test_prose_packs_around_a_whole_code_block(chunker):
    """Blocks are the packing unit: prose splits *between* paragraphs and the
    code block, never through the code block -- not even at the blank lines
    inside the fence, which the paragraph accumulators would happily cut at."""
    groups = "\n\n".join(
        "\n".join(f"line_{g}_{i} = {i}" for i in range(5)) for g in range(12)
    )
    doc = make_doc(
        "# A\n\n" + "p" * 600 + "\n\n```python\n" + groups + "\n```\n\n" + "q" * 600 + "\n"
    )
    chunks = chunker.chunk(doc)

    code = [c for c in chunks if "```python" in c.text]
    assert len(code) == 1, "the code block must land whole in one chunk"
    assert not code[0].split_atomic
    assert code[0].text.rstrip().endswith("```"), "the closer must ride with it"


# --- Task 11: noise dropping, counted not silent (design spec 6.3.3 step 8) ---


def test_html_only_section_is_dropped_and_counted(chunker):
    """Real example: `/specification/.../authorization.md` carries a section
    whose entire body is `<div id="enable-section-numbers" />`."""
    doc = make_doc(
        "# Authorization\n\n"
        "## Real\n\nActual content here.\n\n"
        "## Stub\n\n<div id=\"enable-section-numbers\" />\n"
    )
    chunks = chunker.chunk(doc)

    assert all("enable-section-numbers" not in c.text for c in chunks)
    assert chunker.last_dropped == 1


def test_last_dropped_resets_per_document(chunker):
    """The fairness check reuses one chunker across all 774 corpus documents,
    so ``last_dropped`` must mean "dropped by the most recent ``chunk()``
    call" -- a running counter would smear every document's drops over every
    later one."""
    chunker.chunk(make_doc("# A\n\n## Stub\n\n<div id=\"x\" />\n"))
    assert chunker.last_dropped == 1

    chunks = chunker.chunk(make_doc("# B\n\nReal content.\n"))
    assert chunker.last_dropped == 0
    assert len(chunks) == 1
