"""The ``Source`` abstraction -- design spec 4.3 and 6.1.2.

A source holds a **pointer**, never a copy. That is the whole corpus-layer
argument: uploads create snapshots, and a snapshot goes stale with no way for
the system to notice. Re-reading a pointer on every run removes the staleness
problem instead of managing it.

Three methods, each earning its place:

* ``discover`` -- what does this source currently expose?
* ``fetch``    -- read one of those things, now.
* ``refreshable`` -- can that happen without a human? (``snapshot`` sources: no,
  which is precisely why the project does not build an upload flow.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from docsentry.models import DocRef, SourceKind


@dataclass
class Fetched:
    """Raw bytes for one reference, plus when they were retrieved.

    ``content_type`` is the server's own claim about those bytes -- the HTTP
    ``Content-Type`` header, or ``None`` for a source with no server to ask
    (``local_dir`` reads files). It is carried because a source can be told to
    expect Markdown and be handed an HTML page with a 200; the pipeline decides
    what it will ingest, and it needs the claim to decide with.
    """

    ref: DocRef
    data: bytes
    fetched_at: datetime
    content_type: str | None = None


@runtime_checkable
class Source(Protocol):
    name: str
    kind: SourceKind

    def discover(self) -> list[DocRef]:
        """Every document reference this source currently exposes, sorted."""
        ...

    def fetch(self, ref: DocRef) -> Fetched:
        """Read one reference's current bytes. Raises on failure."""
        ...

    def refreshable(self) -> bool:
        """True when the source can be re-polled with no human in the loop."""
        ...
