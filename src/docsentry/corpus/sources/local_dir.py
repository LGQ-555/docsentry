"""``local_dir`` source: a directory of documents already on disk.

Nothing is copied. The design's rule -- register a pointer, never upload a
copy -- means the directory *is* the corpus: every run re-scans it, and the
manifest hash-compares what comes back, so an edit is noticed without a watcher
process. That is why there is no ``watchdog`` dependency anywhere in this
project (design spec 6.1.2): indexing is a batch job, and re-scanning is
simpler and sufficient.

This is the path a private corpus takes -- an internal wiki export, a
handbook, a vendor SDK dump. No ``llms.txt`` required.
"""

from __future__ import annotations

from pathlib import Path

from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, utcnow


class LocalDirectorySource:
    def __init__(
        self,
        *,
        name: str,
        path: Path | str,
        default_version: str | None = None,
        patterns: tuple[str, ...] = ("*.md",),
    ) -> None:
        self.name = name
        self.kind = SourceKind.LOCAL_DIR
        self.path = Path(path)
        self.default_version = default_version
        self.patterns = tuple(patterns)

    def refreshable(self) -> bool:
        return True

    def discover(self) -> list[DocRef]:
        """Every matching file under the directory, absolute paths, sorted.

        A missing directory yields nothing rather than raising: the source may
        legitimately be empty (the shipped config disables it for that reason),
        and a hard failure here would abort the whole fetch run.
        """
        if not self.path.is_dir():
            return []

        refs: list[DocRef] = []
        for pattern in self.patterns:
            for file in self.path.rglob(pattern):
                if not file.is_file():
                    continue
                refs.append(
                    DocRef(
                        source=self.name,
                        kind=self.kind,
                        locator=str(file.resolve()),
                        version_hint=self.default_version,
                        title="",  # derived from the document's first heading
                    )
                )
        refs.sort(key=lambda ref: ref.locator)
        return refs

    def fetch(self, ref: DocRef) -> Fetched:
        """Read current bytes. Sees edits immediately -- there is no cache."""
        return Fetched(
            ref=ref,
            data=Path(ref.locator).read_bytes(),
            fetched_at=utcnow(),
        )
