"""``MarkdownConverter`` -- the only mandatory converter (design spec 6.2).

Beyond reading the file it does two small normalisations, both of which exist
because of what the real corpora look like:

* **Strips the page-top ``> ## Documentation Index`` banner.** Every MCP and
  LangChain page carries one: measured at 186 characters, byte-identical across
  the corpus. Its cost is not corpus size -- that is 0.53%, since pages run to
  tens of KB -- but *position*: it sits at the head of every document, so it
  eats 18.6% of the 1000-character first chunk and pulls each one's embedding
  toward a common direction. (BM25 largely discounts it on its own: terms that
  appear in *every* document get an IDF near zero.) Only a *leading* blockquote
  is considered, and only when it actually says "Documentation Index", so
  genuine blockquote content is never eaten.
* **Derives a title from the first heading**, skipping fenced code so a ``#``
  comment inside a shell snippet is not mistaken for a title. ``llms_txt``
  sources supply titles already; this is what makes a bare ``local_dir`` usable.
"""

from __future__ import annotations

import re
from pathlib import Path

from docsentry.corpus.converters.base import ConvertedDoc

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_BANNER_MARKER = "Documentation Index"


def strip_index_banner(text: str) -> str:
    """Drop a leading ``> ## Documentation Index`` blockquote, if present."""
    lines = text.splitlines(keepends=True)

    end = 0
    while end < len(lines) and lines[end].lstrip().startswith(">"):
        end += 1
    if end == 0:
        return text
    if _BANNER_MARKER not in "".join(lines[:end]):
        return text  # a real blockquote at the top -- leave it alone

    while end < len(lines) and not lines[end].strip():
        end += 1
    return "".join(lines[end:])


def first_heading(text: str) -> str:
    """First ATX heading outside a fenced code block, or ``""``."""
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


class MarkdownConverter:
    supported = {".md", ".markdown"}

    def convert(self, path: Path) -> ConvertedDoc:
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = strip_index_banner(raw)
        return ConvertedDoc(text=text, title=first_heading(text), origin_format="md")
