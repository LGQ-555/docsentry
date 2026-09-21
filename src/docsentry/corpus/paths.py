"""Locator -> on-disk path, with the guard rails that implies.

An ``llms.txt`` is remote, untrusted input: nothing stops it from listing
``https://host/../../etc/passwd.md`` or a path full of Windows-illegal
characters. Every write and every unlink goes through here first.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

# Characters Windows refuses in a filename, plus control characters.
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')


def _sanitize(part: str) -> str:
    cleaned = _ILLEGAL.sub("_", part).strip().rstrip(".")
    return cleaned or "_"


def raw_relpath(locator: str) -> Path:
    """``<host>/<url path>`` for a locator -- callers join it under their own
    source directory, so a source can never address another's subtree.

    The host is part of the path so two hosts never collide. ``..`` segments
    are dropped rather than resolved -- a document URL never legitimately
    contains one, and dropping is safer than guessing.

    Segments are sanitised *before* any ``Path`` is built, and that order
    matters: on Windows a ``:`` inside a segment is read as a drive separator,
    which silently discards everything preceding it -- including the host, and
    with it the no-collision guarantee. The query string is dropped, matching
    standard URL semantics.
    """
    parsed = urlparse(locator)
    is_web = parsed.scheme in ("http", "https")

    segments = [_sanitize(part) for part in parsed.path.lstrip("/").split("/")]
    segments = [part for part in segments if part != "_"]

    if not segments:
        raise ValueError(f"cannot derive a path from locator {locator!r}")

    if is_web and parsed.netloc:
        return Path(_sanitize(parsed.netloc), *segments)
    return Path(*segments)


def ensure_within(path: Path, root: Path) -> Path:
    """Return ``path`` resolved, or raise if it escapes ``root``.

    A backstop for the sanitising above: called immediately before every write
    and unlink, so a bug in path derivation cannot turn into a write outside
    the corpus tree.
    """
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"refusing to touch {resolved}: outside {root_resolved}")
    return resolved
