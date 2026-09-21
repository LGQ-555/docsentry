"""``llms_txt`` source: a docs site that publishes an index of its own pages.

Two index shapes exist in the wild and both must work -- design spec 6.1.3:

* **flat** -- ``modelcontextprotocol.io/llms.txt`` lists ``.md`` pages directly.
* **hierarchical** -- ``docs.langchain.com/llms.txt`` lists *sub-indexes*
  (other ``llms.txt`` files), which are expanded recursively.

That is a simplification, and the measured corpus contradicts it in one place:
LangChain's top-level index carries **both** shapes in the *same file* -- 58
sub-index links under ``### Section indexes`` plus 119 direct ``.md`` links
under ``## Docs`` / ``## Open source`` / ``## LangSmith Fleet`` /
``## Agent Server API``. So discovery walks both paths in a single pass rather
than branching on "which kind of file is this".

Recursion is capped at ``max_depth`` and guarded by a visited set, so a site
that links back to its own root cannot loop. Measured on the real corpora,
LangChain needs exactly one level; the cap is a safety net, not a working
constraint.

Note there is no ETag / conditional-GET path. MCP serves no ETag and its
``Last-Modified`` is the site *build* time rather than the page's, so a full
body hash is the only trustworthy change signal -- every run re-downloads.
At ~700 pages that is a few seconds and ~14 MB.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from docsentry.corpus.sources.base import Fetched
from docsentry.corpus.versioning import prune_to_latest
from docsentry.models import DocRef, SourceKind, utcnow

# ``- [Title](url): description`` -- the description is optional.
_ENTRY_RE = re.compile(
    r"^\s*[-*]\s*\[(?P<title>[^\]]*)\]\((?P<url>[^)\s]+)\)\s*(?::\s*(?P<desc>.*))?$"
)

# Root index is depth 0; sub-indexes may nest two levels below it.
MAX_INDEX_DEPTH = 2


def parse_llms_txt(text: str, base: str = "") -> list[tuple[str, str, str]]:
    """Parse an ``llms.txt`` into ``(title, url, description)`` triples.

    Headings, prose and blockquotes are skipped: only list entries that carry a
    markdown link count. Relative URLs resolve against ``base``.
    """
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = _ENTRY_RE.match(line)
        if not match:
            continue
        url = match.group("url").strip()
        if not url:
            continue
        entries.append(
            (
                match.group("title").strip(),
                urljoin(base, url) if base else url,
                (match.group("desc") or "").strip(),
            )
        )
    return entries


def _normalize(url: str) -> str:
    """Key for the visited set: scheme/host case- and fragment-insensitive."""
    parts = urlparse(url)
    return urlunparse((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.params, "", ""))


class LlmsTxtSource:
    """Holds the URL of an index, not a copy of the pages it lists."""

    def __init__(
        self,
        *,
        name: str,
        llms_txt: str,
        url_include: tuple[str, ...] | list[str] = (),
        keep_all_versions: bool = True,
        max_depth: int = MAX_INDEX_DEPTH,
        client: httpx.Client | None = None,
        timeout_s: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.llms_txt = llms_txt
        self.url_include = tuple(url_include)
        self.keep_all_versions = keep_all_versions
        self.max_depth = max_depth
        self._client = client
        self._timeout_s = timeout_s
        self._retries = retries

    @property
    def client(self) -> httpx.Client:
        """Lazily built so tests can inject a ``MockTransport`` client."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout_s,
                follow_redirects=True,
                transport=httpx.HTTPTransport(retries=self._retries),
            )
        return self._client

    def refreshable(self) -> bool:
        return True

    def discover(self) -> list[DocRef]:
        """Walk the index tree and return every reachable ``.md`` page, sorted.

        With ``keep_all_versions: false`` the result is pruned to the newest
        version per page *here*, at discovery time -- so the older versions
        simply vanish from the discovered set and flow into the pipeline's
        normal delete phase, rather than needing a separate purge path.
        """
        found: dict[str, DocRef] = {}
        self._expand(self.llms_txt, depth=0, visited=set(), out=found)

        refs = list(found.values())
        if not self.keep_all_versions:
            refs = prune_to_latest(refs)
        # Sorted last, on both paths: ``prune_to_latest`` emits versionless
        # pages first and one entry per version group after, which is sorted
        # only by accident. The contract lives in ``Source.discover``.
        return sorted(refs, key=lambda ref: ref.locator)

    def included(self, url: str) -> bool:
        """Does ``url`` pass the configured include filter?

        Applied to sub-index URLs too, so an unrelated branch of a site is
        never fetched at all -- worth ~50 requests on ``docs.langchain.com``.
        """
        if not self.url_include:
            return True
        return any(needle in url for needle in self.url_include)

    def _expand(self, index_url: str, *, depth: int, visited: set[str], out: dict[str, DocRef]) -> None:
        key = _normalize(index_url)
        if key in visited or depth > self.max_depth:
            return
        visited.add(key)

        for title, url, _description in parse_llms_txt(self._get_text(index_url), base=index_url):
            if not self.included(url):
                continue
            if url.endswith("llms.txt"):
                self._expand(url, depth=depth + 1, visited=visited, out=out)
            elif url.endswith(".md"):
                out.setdefault(
                    url,
                    DocRef(
                        source=self.name,
                        kind=self.kind,
                        locator=url,
                        version_hint=None,  # version comes from the URL path, in versioning.py
                        title=title,
                    ),
                )
            # anything else -- directory entries ending in "/", extensionless
            # pages -- is not a markdown document and is skipped

    def _get_text(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    def fetch(self, ref: DocRef) -> Fetched:
        """Download one page's raw bytes.

        Returns bytes rather than text: ``response.content`` is the body *after*
        content-encoding is undone (MCP serves gzip) but *before* any text
        decoding. Hashing that is stable if the server switches compression,
        and a future non-UTF-8 format is not silently mangled on the way in.
        """
        response = self.client.get(ref.locator)
        response.raise_for_status()
        return Fetched(ref=ref, data=response.content, fetched_at=utcnow())
