import json
from datetime import datetime, timezone

import pytest

from docsentry.corpus.manifest import Manifest, ManifestEntry, ManifestUnreadable


def _entry(content_hash="abc", version="2026-07-28", fetched_at=None):
    return ManifestEntry(
        content_hash=content_hash,
        version=version,
        fetched_at=fetched_at or datetime(2026, 9, 20, tzinfo=timezone.utc),
    )


def test_new_manifest_is_empty():
    assert len(Manifest()) == 0
    assert Manifest().locators() == set()


def test_set_then_get():
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry())

    assert manifest.get("https://x/a.md").content_hash == "abc"
    assert "https://x/a.md" in manifest
    assert manifest.get("https://x/nope.md") is None


def test_remove():
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry())

    manifest.remove("https://x/a.md")

    assert "https://x/a.md" not in manifest
    assert manifest.locators() == set()


def test_remove_of_unknown_locator_is_a_noop():
    manifest = Manifest()

    manifest.remove("https://x/nope.md")  # must not raise

    assert len(manifest) == 0


def test_save_then_load_round_trip(tmp_path):
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry(content_hash="h1", version="2026-07-28"))
    manifest.set("https://x/b.md", _entry(content_hash="h2", version="draft"))
    path = tmp_path / "manifest.json"

    manifest.save(path)
    restored = Manifest.load(path)

    assert restored.locators() == manifest.locators()
    assert restored.get("https://x/a.md").content_hash == "h1"
    assert restored.get("https://x/b.md").version == "draft"


def test_load_missing_file_returns_empty(tmp_path):
    # A first run has no baseline to lose, so this is the one silent case.
    assert len(Manifest.load(tmp_path / "nope.json")) == 0


def test_load_corrupt_file_raises(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ManifestUnreadable) as excinfo:
        Manifest.load(path)

    # The caller (fetch_corpus.py) has to say what is wrong and which file to
    # fix, so the diagnosis travels with the exception.
    assert excinfo.value.path == path
    assert str(path) in str(excinfo.value)
    assert "not valid JSON" in excinfo.value.reason


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "manifest.json"

    Manifest().save(path)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "manifest.json"

    Manifest().save(path)

    assert path.exists()


def test_saved_json_is_sorted_and_human_readable(tmp_path):
    manifest = Manifest()
    manifest.set("https://x/b.md", _entry())
    manifest.set("https://x/a.md", _entry())
    path = tmp_path / "manifest.json"

    manifest.save(path)

    text = path.read_text(encoding="utf-8")
    assert text.index("https://x/a.md") < text.index("https://x/b.md")
    assert json.loads(text)["https://x/a.md"]["version"] == "2026-07-28"


def test_manifest_does_not_store_paths():
    # Paths are derived from the locator; storing them would be a second
    # source of truth that can drift.
    keys = set(ManifestEntry(content_hash="h", version="v", fetched_at=datetime.now(timezone.utc)).to_json())

    assert keys == {"content_hash", "version", "fetched_at"}


# --- a file that is present but cannot be honoured is not "no file" --------


def test_load_undecodable_file_raises(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff\xfe{}")  # not UTF-8

    with pytest.raises(ManifestUnreadable, match="unreadable"):
        Manifest.load(path)


def test_load_wrong_shaped_json_raises(tmp_path):
    # Valid JSON, but not a manifest -- each of these used to escape as
    # AttributeError / TypeError / KeyError from the entry loop.
    payloads = [
        "[]",
        "null",
        '"hello"',
        '{"https://x/a.md": null}',
        '{"https://x/a.md": "nope"}',
        '{"https://x/a.md": {"content_hash": "h"}}',
    ]
    path = tmp_path / "manifest.json"

    for payload in payloads:
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(ManifestUnreadable, match="unreadable"):
            Manifest.load(path)


def test_load_io_failure_raises(tmp_path):
    # A directory where the file should be: "I cannot read this", not "absent".
    # Windows raises PermissionError here where POSIX raises IsADirectoryError
    # -- which is the point of catching OSError rather than naming subtypes.
    path = tmp_path / "manifest.json"
    path.mkdir()

    with pytest.raises(ManifestUnreadable, match="unreadable"):
        Manifest.load(path)


def test_unreadable_is_not_an_oserror():
    # Pinned on purpose: an `except OSError` around a load call must not be
    # able to turn "the baseline is damaged" back into "start over silently".
    assert not issubclass(ManifestUnreadable, OSError)
