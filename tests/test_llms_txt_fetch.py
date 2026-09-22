import httpx
import pytest

from docsentry.corpus.sources.llms_txt import LlmsTxtSource
from docsentry.models import DocRef, SourceKind

ROOT = "https://docs.example.com/llms.txt"


def _source(pages: dict[str, str], binary: dict[str, bytes] | None = None) -> LlmsTxtSource:
    binary = binary or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in binary:
            return httpx.Response(200, content=binary[url])
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404)

    return LlmsTxtSource(name="example", llms_txt=ROOT, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ref(locator: str) -> DocRef:
    return DocRef(source="example", kind=SourceKind.LLMS_TXT, locator=locator)


def test_fetch_returns_raw_bytes():
    source = _source({}, binary={"https://docs.example.com/a.md": "# A\nbody\n".encode("utf-8")})

    fetched = source.fetch(_ref("https://docs.example.com/a.md"))

    assert fetched.data == "# A\nbody\n".encode("utf-8")
    assert fetched.ref.locator == "https://docs.example.com/a.md"


def test_fetch_records_a_timestamp():
    source = _source({}, binary={"https://docs.example.com/a.md": b"# A\n"})

    fetched = source.fetch(_ref("https://docs.example.com/a.md"))

    assert fetched.fetched_at.tzinfo is not None


def test_fetch_carries_the_servers_content_type():
    """The pipeline refuses a page the server did not send as markdown."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!DOCTYPE html>", headers={"content-type": "text/html; charset=utf-8"})

    source = LlmsTxtSource(name="example", llms_txt=ROOT, client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert source.fetch(_ref("https://docs.example.com/a.md")).content_type == "text/html; charset=utf-8"


def test_fetch_without_a_content_type_header_reports_none():
    source = _source({}, binary={"https://docs.example.com/a.md": b"# A\n"})

    assert source.fetch(_ref("https://docs.example.com/a.md")).content_type is None


def test_fetch_encodes_non_ascii_as_utf8():
    body = "# 中文标题\n内容\n".encode("utf-8")
    source = _source({}, binary={"https://docs.example.com/a.md": body})

    assert source.fetch(_ref("https://docs.example.com/a.md")).data.decode("utf-8") == "# 中文标题\n内容\n"


def test_fetch_raises_on_404():
    source = _source({})

    with pytest.raises(httpx.HTTPStatusError):
        source.fetch(_ref("https://docs.example.com/missing.md"))


def test_refreshable_is_true():
    assert _source({}).refreshable() is True


def test_discover_then_fetch_round_trip():
    source = _source(
        {ROOT: "- [A](https://docs.example.com/a.md)\n"},
        binary={"https://docs.example.com/a.md": b"# A\n"},
    )

    ref = source.discover()[0]

    assert source.fetch(ref).data == b"# A\n"
