"""``StructuralChunker`` -- the core of M2 -- design spec 6.3.3.

Walks the ``markdown-it-py`` token stream, keeps a heading stack, and emits one
chunk per section body.

**flush-on-close, not "leaf sections".** The design doc originally said "每个叶子
section 合并为一个 chunk". Implemented literally that drops every non-leaf
section's own body: measured on the real corpus, 19.6 points of coverage. The
worst case is ``build-client.md``, whose 2,522 lines carry exactly two headings
-- the 80,448-character tutorial hangs under the H1, so the literal reading
emits only the 172 characters of "Next steps" and the page that teaches MCP
client building is unreachable. Text belongs to the section it is written
under, not to the section that happens to have no children.

**Atomic units get a hard ceiling -- M2 design decision 2, main spec 6.3.3
step 6.** The literal "code blocks and tables are never cut" rule produced a
measured 106,728-character chunk (LangChain's "All tools and toolkits"
table) and a batch of 80,000-90,000-character ones (MCP's
``build-server.md`` / ``build-client.md``, six versions each). Such chunks
fail silently: the embedding truncates and the prompt cannot hold them. So
an atomic unit is kept whole up to ``max_atomic_size`` (4,000) -- the
design's one exception to the shared ``target_size`` -- and cut above it:
tables row-by-row with the header repeated in every piece, code at
top-level ``def`` / ``class`` / ``function`` boundaries (a heuristic that
may cut mid-construct), and unbroken prose runs by plain hard cuts (measured
on the 2026-09-24 corpus: 176 prose runs exceed 4,000 characters, the
106,285-character one included -- ``schema.md``'s JSON blocks and the
frontend pages' glued quote lines). Every forced cut sets
``split_atomic=True`` so the evaluation reports these chunks separately: the
system does not pretend it never cut an atomic unit -- the main spec's
honesty principle (6.9), applied to chunking by the M2 design's decision 2.

**Noise is dropped, counted, never silent -- M2 design decision 3, main spec
6.3.3 step 8.** A section whose body is empty after stripping HTML tags (the
corpus's ``<div id="enable-section-numbers" />`` stubs, image-only ``<Frame>``
wrappers) produces no chunk, and every drop increments ``last_dropped`` so the
report can publish the count. Short sections are *not* merged or dropped --
corpus sampling found they are mostly precise API fragments, which is exactly
the granularity developers query at (see ``is_noise`` in ``base.py``).
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

from docsentry.chunking.base import accumulate_paragraphs, is_noise
from docsentry.config import ChunkingConfig
from docsentry.models import Chunk, Document, make_chunk_id

_MD = MarkdownIt("commonmark")

# Same fence heuristic as ``_classify`` -- indented openers count, info
# strings containing a backtick mis-toggle. Accepted divergence, damage
# bounded to a misclassified block. ``_TOP_LEVEL_RE`` and ``_DELIM_RE`` are
# the cut-point heuristics of decision 2's forced degradation.
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_TOP_LEVEL_RE = re.compile(r"^(def |class |function |async def |async function )")
_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass
class _Open:
    """A heading currently on the stack, with whatever body has accumulated."""

    level: int
    title: str
    body: list[str] = field(default_factory=list)


class StructuralChunker:
    name = "structural"

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config
        # Dropped-chunk count for this document. Reported, never silent --
        # a chunk that disappears without a number is indistinguishable from
        # one that was never produced.
        self.last_dropped = 0

    def chunk(self, doc: Document) -> list[Chunk]:
        # Per-document semantics: the fairness check reuses one chunker across
        # every corpus document, and ``last_dropped`` must mean "dropped by the
        # most recent ``chunk()`` call", not "dropped since the process began".
        self.last_dropped = 0
        try:
            sections = self._sections(doc.content)
        except Exception as exc:  # noqa: BLE001 -- design spec 6.3.3
            # Degrade rather than produce nothing, but say so: a document that
            # silently loses its whole heading structure is indistinguishable
            # from one that never had any.
            warnings.warn(
                f"structural chunking fell back to paragraph accumulation for "
                f"{doc.url!r}: {type(exc).__name__}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            sections = [(self._fallback_breadcrumb(doc),
                         [(piece, False)
                          for piece in accumulate_paragraphs(doc.content, self.config.target_size)])]

        texts: list[tuple[list[str], str, bool]] = []
        for breadcrumb, pieces in sections:
            texts.extend((breadcrumb, piece, atomic) for piece, atomic in pieces)

        chunks: list[Chunk] = []
        for ordinal, (breadcrumb, text, atomic) in enumerate(texts):
            body = text.strip()
            if not body or is_noise(body):
                self.last_dropped += 1
                continue
            chunks.append(Chunk(
                chunk_id=make_chunk_id(doc.doc_id, ordinal, self.name),
                doc_id=doc.doc_id,
                text=text,
                breadcrumb=breadcrumb,
                source=doc.source,
                version=doc.version,
                url=doc.url,
                kind=self._classify(text),
                strategy=self.name,
                char_count=len(text),
                split_atomic=atomic,
            ))
        return chunks

    def _sections(self, content: str) -> list[tuple[list[str], list[tuple[str, bool]]]]:
        """Return ``[(breadcrumb, [(piece, split_atomic), ...])]`` for every
        section with a body, **in document order**.

        Two things are load-bearing here:

        * **The token stream only locates the headings; the body is sliced by
          line number.** Accumulating straight from ``token.map`` duplicates
          text -- ``heading_open`` and the ``inline`` after it share one map,
          and ``paragraph_open`` / ``inline`` / ``paragraph_close`` share
          theirs, so each line is appended once per token covering it, and the
          heading line itself lands in the body.
        * **A section's body is emitted the moment a heading opens inside it**,
          not when the section is popped. The body precedes the child, so
          emitting on pop reverses the document order (C, B, A instead of
          A, B, C) and files each body under the wrong breadcrumb.

        A heading that later gains a child still owns the text before that
        child: emitting only leaf sections -- the design doc's literal wording
        -- drops 19.6 points of the corpus, including the whole of
        ``build-client.md``.
        """
        lines = content.splitlines(keepends=True)
        tokens = _MD.parse(content)
        headings: list[tuple[int, int, str]] = []
        for i, token in enumerate(tokens):
            if token.type != "heading_open" or not token.map:
                continue
            title = _heading_text(lines, token.map[0])
            if not title and i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                # Headings the raw-line regex cannot title: CommonMark
                # accepts up to three leading spaces before ``#``, and a
                # heading may open inside a list item (``* ### ...``).
                # markdown-it still emits ``heading_open`` for both -- without
                # this fallback the section files under an empty breadcrumb
                # component. Measured: 82 of 11,571 corpus headings.
                title = tokens[i + 1].content.strip()
            headings.append((token.map[0], int(token.tag[1]), title))

        out: list[tuple[list[str], list[tuple[str, bool]]]] = []
        stack: list[_Open] = []

        def emit(frame: _Open) -> None:
            # `stack` still contains `frame` and its ancestors, so the
            # breadcrumb is complete. Clearing the body means a parent emitted
            # ahead of its child is not emitted again when it is popped.
            pieces = self._split(frame.body)
            if pieces:
                out.append(([f.title for f in stack], pieces))
            frame.body = []

        for idx, (line_no, level, title) in enumerate(headings):
            # Close every section at this level or deeper: the new heading is
            # outside each of them, so their bodies are complete.
            while stack and stack[-1].level >= level:
                emit(stack[-1])
                stack.pop()
            # The new heading opens *inside* whatever is now on top, so that
            # section's own body ends here.
            if stack:
                emit(stack[-1])
            end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
            stack.append(_Open(level=level, title=title, body=lines[line_no + 1:end]))

        while stack:
            emit(stack[-1])
            stack.pop()
        return out

    def _split(self, body_lines: list[str]) -> list[tuple[str, bool]]:
        """Return ``[(text, split_atomic)]``.

        Code blocks and tables are atomic -- never cut mid-unit -- *unless*
        the unit exceeds ``max_atomic_size``, at which point cutting is
        mandatory rather than optional (M2 design decision 2; main spec
        6.3.3 step 6). The alternative is a chunk the embedding model
        truncates and the prompt cannot hold, which fails silently; cutting
        and flagging it fails visibly instead -- the honesty principle the
        main spec states in 6.9, which the M2 design's decision 2 explicitly
        invokes.

        Note the asymmetry: an atomic unit is allowed to exceed
        ``target_size`` (the design's stated exception to the fairness
        constraint), but not ``max_atomic_size``. Those are two different
        ceilings and only the first one is negotiable.

        Everything else packs to ``target_size`` at block boundaries: a
        block is never cut internally, so a section of prose around a
        mid-size code block splits *between* the paragraphs and the code
        block, never through the code block -- not even at the blank lines
        inside the fence, where the paragraph accumulators would cut. One
        consequence: an unbroken prose run (no blank line, no fence, no pipe
        row) lands whole no matter its size, so a run over the ceiling is
        hard-cut and flagged like an atomic unit rather than silently left
        to the embedding's truncation.
        """
        text = "".join(body_lines).strip()
        if not text:
            return []

        blocks = _segment(text)
        pieces: list[tuple[str, bool]] = []
        buffer = ""
        for kind, block in blocks:
            if len(block) > self.config.max_atomic_size:
                if buffer.strip():
                    pieces.append((buffer.strip(), False))
                    buffer = ""
                pieces.extend((piece, True) for piece in _cut_atomic(kind, block, self.config))
                continue
            if buffer and len(buffer) + len(block) + 1 > self.config.target_size:
                pieces.append((buffer.strip(), False))
                buffer = block
            else:
                buffer = f"{buffer}\n{block}" if buffer else block
        if buffer.strip():
            pieces.append((buffer.strip(), False))
        return pieces

    def _classify(self, text: str) -> str:
        """Label one chunk's dominant structure -- design spec 6.3.3 step 7,
        M2 design 4.2: fenced code over 70% is ``code``, tabular lines over
        70% are ``table``, over 30% combined structure is ``mixed``, else
        ``prose``.

        Judged on the **final chunk text**, never the whole section: a section
        that is prose for its first 1,000 characters and a table afterwards
        must label its first piece ``prose`` and its second ``table``.
        Judging the section would smear one label over every piece of it, and
        ``mixed`` is the honest answer only for pieces that really mix.

        Raw-line heuristics, not the ``markdown-it`` token stream, and
        deliberately so: by the time this runs, the text is a *piece* of a
        section body while token maps index the whole document's lines, and
        re-parsing each piece alone would lose the fence context that the
        piece's neighbours carry. A line-prefix scan is the honest tool at
        this granularity. Two divergences from a strict parse are accepted:

        * Prefix detection does not implement the info-string rule. A line
          opening with ``` whose info string contains a backtick is not a
          fence opener in CommonMark, and a shorter nested fence does not
          close a longer one -- both toggle ``in_fence`` wrongly. The damage
          is bounded: each mis-toggle mis-counts a few lines against the 70%
          threshold, and the only failure mode is a mislabelled ``kind``.
          No content is lost or moved; the label is metadata, not retrieval.
        * A 4-space-indented code-block line beginning with ``` is counted as
          fenced. For "is this code?", that is the right answer by the wrong
          mechanism -- and after the MDX dedent fix (M2 design 3), indented
          blocks are rare in the corpus anyway.

        ``mixed`` at > 30% combined reads the spec's "皆有" as "structure is
        present in a meaningful share" rather than the literal "contains both
        a fence and a table": a chunk that is 35% code and 65% prose is not
        honestly ``prose``. Measured on the 2026-09-24 corpus, the literal
        reading would label ~20 of 17,379 chunks ``mixed`` -- a bucket that
        almost never fires is no bucket -- while 30% combined labels 2,826.

        Since Task 10, ``_split`` never cuts a fence unless the block exceeds
        ``max_atomic_size``, so a chunk ends mid-fence only when it is a
        flagged ``split_atomic`` piece of such a forced cut, or when the
        source document itself leaves a fence unclosed (13 chunks on the
        2026-09-24 corpus -- the chunk reproduces the source faithfully
        there). Those fragments are judged on text that starts or ends
        mid-fence, and the toggle then miscounts every line on the wrong side
        of it -- the failure mode is a mislabelled ``kind`` on chunks the
        evaluation already reports separately (or on a source that was
        malformed to begin with), so it stays a bounded, honest mislabel
        rather than a reason to make this heuristic cleverer.
        """
        fenced = 0
        tabular = 0
        in_fence = False
        for line in text.splitlines(keepends=True):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                fenced += len(line)
                continue
            if in_fence:
                fenced += len(line)
            elif line.lstrip().startswith("|"):
                tabular += len(line)
        total = len(text) or 1
        if fenced / total > 0.7:
            return "code"
        if tabular / total > 0.7:
            return "table"
        if (fenced + tabular) / total > 0.3:
            return "mixed"
        return "prose"

    def _fallback_breadcrumb(self, doc: Document) -> list[str]:
        return [doc.title] if doc.title else []


def _segment(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(kind, block)`` where kind is code | table | prose.

    The boundaries are the structural ones, so a block is the unit
    ``_split`` packs and never cuts inside:

    * blank lines, as in the paragraph accumulators;
    * fence lines, which are unambiguous block boundaries in Markdown --
      prose glued to a closing fence (no blank line) must not ride into the
      code block, or ``_cut_atomic`` would cut it as code;
    * pipe-line runs: a table glued to a following paragraph must not make
      the paragraph a table row, or every piece of a forced cut would repeat
      the header over prose.

    The fence scan is the same heuristic as ``_classify`` with the same
    accepted divergences (a fence shown *inside* a fence toggles it shut).
    The damage is a block misclassified around the glitch -- never lost or
    moved content, because the lines themselves always land in some block.
    """
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append((_kind_of(current), "".join(current)))
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


def _kind_of(lines: list[str]) -> str:
    """Classify one block by its first line. Load-bearing on ``_segment``'s
    splits: a code block starts with its opener (fence split), a table block
    contains only pipe lines (pipe split), everything else is prose."""
    joined = "".join(lines).lstrip()
    if joined.startswith(("```", "~~~")):
        return "code"
    if joined.startswith("|"):
        return "table"
    return "prose"


def _cut_atomic(kind: str, block: str, config: ChunkingConfig) -> list[str]:
    """Cut one unit that exceeded ``max_atomic_size`` -- decision 2's forced
    degradation. Every returned piece is flagged ``split_atomic=True``.

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


def _heading_text(lines: list[str], line_no: int) -> str:
    # lstrip: CommonMark accepts up to three leading spaces before the hashes
    # and markdown-it emits ``heading_open`` for them -- the unmodified regex
    # returns "" there, and the section's breadcrumb component goes blank.
    match = re.match(r"^#{1,6}\s+(.*?)\s*$", lines[line_no].rstrip("\n\r").lstrip())
    return match.group(1) if match else ""
