"""MDX layout-container normalisation -- design spec 6.2.1.

MCP and LangChain pages are Mintlify-flavoured MDX: tabbed content lives inside
``<Tabs>`` / ``<Tab title="X">`` / ``<CodeGroup>`` and is indented 4-6 spaces.
CommonMark reads indented content as a **code block**, so on the real corpus
1,235,578 characters (8.5%, 211 documents) reach the parser as "code" -- every
heading inside them is invisible, ``kind`` would be judged ``"code"``, and the
chunker's atomic-unit rule would preserve the whole region verbatim.

This module is a pure string transform with no project imports, so it can be
tested without a corpus, a network, or a chunker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
OPEN_RE = re.compile(
    r"^[ \t]*<(?P<tag>[A-Z][A-Za-z0-9]*)"
    r"(?:\s+title=(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'))?"
    r"[^>]*>\s*$"
)
CLOSE_RE = re.compile(r"^[ \t]*</(?P<tag>[A-Z][A-Za-z0-9]*)>\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
TAG_ANY_RE = re.compile(r"^[ \t]*</?[A-Z][A-Za-z0-9]*[^>]*>\s*$")

# Layout containers: their content is real prose/code that must be surfaced.
LAYOUT = frozenset({"Tabs", "Tab", "CodeGroup", "Accordion", "AccordionGroup", "Steps", "Step"})
# Semantic tags: the tag itself carries no structure we preserve -- drop the
# tag, keep the text it wraps.
SEMANTIC = frozenset({"Note", "Warning", "Tip", "Info", "Check", "Card", "CardGroup",
                      "Columns", "Column"})


@dataclass
class Frame:
    """One open layout container."""

    tag: str
    title: str | None
    open_i: int
    close_i: int = -1
    min_indent: int = 0
    titled_depth: int = 0   # titled containers from the outermost ancestor to here
    level: int = 0          # synthetic heading level; 0 means "emit no heading"

    @property
    def index(self) -> int:
        return self.open_i


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def scan(lines: list[str]) -> tuple[list[Frame], list[Frame | None], list[str]]:
    """One pass over ``lines``.

    Returns ``(frames, owner, kind)``:

    * ``frames`` -- every layout container, in nesting order, with ``min_indent``
      filled in (the smallest indent among its own content lines).
    * ``owner``  -- per line, the innermost layout container it belongs to.
    * ``kind``   -- per line, ``"open"`` / ``"close"`` / ``"content"``.
    """
    frames: list[Frame] = []
    stack: list[Frame] = []
    owner: list[Frame | None] = []
    kind: list[str] = []
    in_fence = False

    for i, line in enumerate(lines):
        is_tag = bool(TAG_ANY_RE.match(line))
        marker = bool(FENCE_RE.match(line))

        # Container tags are only recognised outside fences -- a fenced HTML
        # sample must not be mistaken for a container.
        if not in_fence and not marker and is_tag:
            mc = CLOSE_RE.match(line)
            if mc:
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k].tag == mc.group("tag"):
                        stack[k].close_i = i
                        del stack[k:]
                        break
                kind.append("close")
                owner.append(None)
                continue

            mo = OPEN_RE.match(line)
            if mo and mo.group("tag") in LAYOUT:
                title = mo.group("dq") or mo.group("sq")
                frames.append(Frame(
                    tag=mo.group("tag"),
                    title=title,
                    open_i=i,
                    titled_depth=sum(1 for f in stack if f.title) + (1 if title else 0),
                ))
                stack.append(frames[-1])
                kind.append("open")
                owner.append(None)
                continue
            if mo and mo.group("tag") in SEMANTIC:
                kind.append("close")   # dropped either way
                owner.append(None)
                continue

        if marker:
            in_fence = not in_fence

        kind.append("content")
        owner.append(stack[-1] if stack else None)

    for frame in frames:
        if frame.close_i < 0:
            frame.close_i = len(lines)
        # Child container tags count as the frame's own content: a <Tabs> whose
        # only direct children are <Tab> tags has no content lines of its own,
        # yet its content level is exactly the indent those tags sit at (real
        # corpus: 318 of 2362 frames, almost all Tabs/Steps/AccordionGroup).
        mins = [indent_of(lines[i])
                for i in range(frame.open_i + 1, frame.close_i)
                if lines[i].strip() and kind[i] in ("content", "open", "close")]
        frame.min_indent = min(mins) if mins else 0

    return frames, owner, kind


def normalise(text: str) -> str:
    """Flatten MDX layout containers into plain Markdown.

    Three rules, each load-bearing:

    1. **Container tags are removed.** Left in place they open a CommonMark
       HTML block (type 6) that runs to the next blank line, swallowing the
       fence right after ``<CodeGroup>`` -- which is how shell comments inside
       code ended up promoted to H1s.
    2. **Content is dedented by its innermost container's ``min_indent``**
       (absolute, not summed: a line at indent 6 inside containers whose minima
       are 2/4/6 would lose 12 columns if the minima were added).
    3. **Titled containers become synthetic headings**, one level below the
       heading their outermost ancestor hangs under. Without this the seven
       language tabs of ``build-client.md`` produce seven identical subtrees
       competing for the same top-5 slots.
    """
    lines = text.splitlines(keepends=True)
    frames, owner, kind = scan(lines)
    _resolve_levels(lines, frames, kind)

    out: list[str] = []
    for i, line in enumerate(lines):
        if kind[i] != "content":
            frame = next((f for f in frames if f.open_i == i), None)
            if frame is not None and frame.level:
                out.append(f"{'#' * frame.level} {frame.title}\n")
            continue
        if not line.strip():
            out.append(line)
            continue

        frame = owner[i]
        dedent = frame.min_indent if frame else 0
        body = line[dedent:] if len(line) > dedent else line.lstrip(" \t")

        match = HEADING_RE.match(body)
        if match and not _inside_fence(lines, kind, i):
            shift = frame.titled_depth if frame else 0
            if shift:
                body = f"{'#' * min(len(match.group(1)) + shift, 6)} {match.group(2)}"
        out.append(body)

    return "".join(out)


def _resolve_levels(lines: list[str], frames: list[Frame], kind: list[str]) -> None:
    """Give every titled container a heading level.

    Computed statically, not from emit-time state: the previous tab's headings
    leak into the running level and each successive tab comes out one deeper
    (observed h2, h3, h4, h5, h6, h6, h6 before this was made static).
    """
    outside = 0
    level_before: list[int] = []
    in_fence = False
    for i, line in enumerate(lines):
        level_before.append(outside)
        if kind[i] == "content" and FENCE_RE.match(line):
            in_fence = not in_fence
        if kind[i] == "content" and not in_fence:
            match = HEADING_RE.match(line)
            if match and not owner_depth(frames, i):
                outside = len(match.group(1))

    for frame in frames:
        if not frame.title:
            frame.level = 0
            continue
        ancestors = [f for f in frames if f.open_i < frame.open_i < f.close_i]
        base = max((a.level for a in ancestors if a.level), default=level_before[frame.open_i])
        frame.level = min((base or 0) + frame.titled_depth, 6) or min(frame.titled_depth, 6)


def owner_depth(frames: list[Frame], i: int) -> int:
    return sum(1 for f in frames if f.open_i < i < f.close_i)


def _inside_fence(lines: list[str], kind: list[str], upto: int) -> bool:
    state = False
    for j in range(upto):
        if kind[j] == "content" and FENCE_RE.match(lines[j]):
            state = not state
    return state
