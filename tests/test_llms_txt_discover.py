import httpx
import pytest

from docsentry.corpus.sources.llms_txt import LlmsTxtSource, parse_llms_txt

ROOT = "https://docs.example.com/llms.txt"


def _client(pages: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text=f"not found: {url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _source(pages: dict[str, str], **kwargs) -> LlmsTxtSource:
    return LlmsTxtSource(
        name="example",
        llms_txt=ROOT,
        client=_client(pages),
        max_depth=kwargs.pop("max_depth", 2),
        **kwargs,
    )


# --- parse_llms_txt -------------------------------------------------------

def test_parses_title_url_and_description():
    text = "- [Title A](https://docs.example.com/a.md): the description\n"

    assert parse_llms_txt(text) == [("Title A", "https://docs.example.com/a.md", "the description")]


def test_description_is_optional():
    text = "- [Title A](https://docs.example.com/a.md)\n"

    assert parse_llms_txt(text)[0][2] == ""


def test_titles_with_brackets_and_punctuation_survive():
    text = "- [What is the Model Context Protocol (MCP)?](https://docs.example.com/a.md)\n"

    assert parse_llms_txt(text)[0][0] == "What is the Model Context Protocol (MCP)?"


def test_headings_prose_and_blockquotes_are_ignored():
    text = (
        "# Docs by Example\n"
        "> Some prose about the docs.\n"
        "## Section indexes\n"
        "\n"
        "- [Real](https://docs.example.com/a.md)\n"
    )

    assert parse_llms_txt(text) == [("Real", "https://docs.example.com/a.md", "")]


def test_relative_urls_resolve_against_base():
    text = "- [A](/a.md)\n"

    assert parse_llms_txt(text, base=ROOT)[0][1] == "https://docs.example.com/a.md"


# --- discover: flat -------------------------------------------------------

def test_discover_flat_index():
    source = _source({ROOT: "- [A](https://docs.example.com/a.md)\n- [B](https://docs.example.com/b.md)\n"})

    refs = source.discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/a.md",
        "https://docs.example.com/b.md",
    ]
    assert refs[0].source == "example"
    assert refs[0].title == "A"


def test_discover_skips_directory_entries_and_non_md():
    source = _source(
        {
            ROOT: (
                "- [Dir](https://docs.example.com/sub/)\n"
                "- [Page](https://docs.example.com/page)\n"
                "- [Real](https://docs.example.com/a.md)\n"
            )
        }
    )

    assert [r.locator for r in source.discover()] == ["https://docs.example.com/a.md"]


def test_discover_deduplicates_repeated_entries():
    source = _source(
        {
            ROOT: (
                "- [A](https://docs.example.com/a.md)\n"
                "- [A again](https://docs.example.com/a.md)\n"
            )
        }
    )

    assert len(source.discover()) == 1


# --- discover: hierarchical -----------------------------------------------

def test_discover_expands_sub_indexes():
    source = _source(
        {
            ROOT: "- [Python](https://docs.example.com/oss/python/llms.txt)\n",
            "https://docs.example.com/oss/python/llms.txt": (
                "- [A](https://docs.example.com/oss/python/a.md)\n"
                "- [B](https://docs.example.com/oss/python/b.md)\n"
            ),
        }
    )

    assert [r.locator for r in source.discover()] == [
        "https://docs.example.com/oss/python/a.md",
        "https://docs.example.com/oss/python/b.md",
    ]


def test_discover_handles_a_mixed_index():
    """``docs.langchain.com/llms.txt`` carries *both* shapes in one file.

    Sub-index links sit under ``### Section indexes``; 119 direct ``.md`` links
    are spread across the ``## Docs`` / ``## Open source`` / ``## LangSmith
    Fleet`` / ``## Agent Server API`` sections. Discovery must walk both paths
    in a single pass -- it may not branch on "which kind of file is this".
    """
    source = _source(
        {
            ROOT: (
                "# Docs by Example\n"
                "### Section indexes\n"
                "- [Python](https://docs.example.com/oss/python/llms.txt)\n"
                "## Docs\n"
                "- [Direct](https://docs.example.com/docs/direct.md)\n"
            ),
            "https://docs.example.com/oss/python/llms.txt": (
                "- [A](https://docs.example.com/oss/python/a.md)\n"
            ),
        }
    )

    assert [r.locator for r in source.discover()] == [
        "https://docs.example.com/docs/direct.md",
        "https://docs.example.com/oss/python/a.md",
    ]


def test_depth_limit_stops_recursion():
    pages = {
        ROOT: "- [L1](https://docs.example.com/l1/llms.txt)\n",
        "https://docs.example.com/l1/llms.txt": "- [L2](https://docs.example.com/l2/llms.txt)\n",
        "https://docs.example.com/l2/llms.txt": "- [L3](https://docs.example.com/l3/llms.txt)\n",
        "https://docs.example.com/l3/llms.txt": "- [Deep](https://docs.example.com/deep.md)\n",
    }

    # depth 0 = root, 1 = l1, 2 = l2 -> l3 is refused, so deep.md is unreachable
    assert _source(pages, max_depth=2).discover() == []


def test_cycle_between_indexes_terminates():
    pages = {
        ROOT: "- [A](https://docs.example.com/a/llms.txt)\n",
        "https://docs.example.com/a/llms.txt": "- [Back](https://docs.example.com/llms.txt)\n",
    }

    assert _source(pages).discover() == []


def test_self_referencing_index_terminates():
    pages = {
        ROOT: "- [Self](https://docs.example.com/llms.txt)\n- [Real](https://docs.example.com/a.md)\n",
    }

    assert [r.locator for r in _source(pages).discover()] == ["https://docs.example.com/a.md"]


# --- discover: ordering contract ------------------------------------------

def test_discover_is_sorted():
    """Pins the ``sorted`` promise in ``Source.discover``'s docstring.

    Traversal order is not naturally sorted: a hierarchical walk follows the
    index's own section order, and the kept entries come out of a dict.
    """
    source = _source(
        {
            ROOT: (
                "- [Z](https://docs.example.com/z.md)\n"
                "- [A](https://docs.example.com/a.md)\n"
            )
        }
    )

    assert [r.locator for r in source.discover()] == [
        "https://docs.example.com/a.md",
        "https://docs.example.com/z.md",
    ]


def test_discover_is_sorted_when_pruning():
    """``prune_to_latest`` returns versionless pages first, then one per group,
    so the pruned branch is *not* sorted by construction -- discover must sort
    its result on both paths, not just the ``keep_all_versions`` one."""
    source = _source(
        {
            ROOT: (
                "- [Old](https://docs.example.com/docs/2025-11-25/a.md)\n"
                "- [New](https://docs.example.com/docs/2026-07-28/a.md)\n"
                "- [Sep](https://docs.example.com/seps/1-a.md)\n"
            )
        },
        keep_all_versions=False,
    )

    assert [r.locator for r in source.discover()] == [
        "https://docs.example.com/docs/2026-07-28/a.md",
        "https://docs.example.com/seps/1-a.md",
    ]


# --- discover: url_include ------------------------------------------------

def test_url_include_filters_pages_and_sub_indexes():
    pages = {
        ROOT: (
            "- [Py](https://docs.example.com/oss/python/llms.txt)\n"
            "- [JS](https://docs.example.com/oss/javascript/llms.txt)\n"
        ),
        "https://docs.example.com/oss/python/llms.txt": "- [A](https://docs.example.com/oss/python/a.md)\n",
        "https://docs.example.com/oss/javascript/llms.txt": "- [B](https://docs.example.com/oss/javascript/b.md)\n",
    }

    refs = _source(pages, url_include=["/oss/python/"]).discover()

    assert [r.locator for r in refs] == ["https://docs.example.com/oss/python/a.md"]


def test_multiple_url_include_needles_union():
    pages = {
        ROOT: (
            "- [A](https://docs.example.com/docs/a.md)\n"
            "- [B](https://docs.example.com/specification/b.md)\n"
            "- [C](https://docs.example.com/seps/c.md)\n"
        )
    }

    refs = _source(pages, url_include=["/docs/", "/specification/"]).discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/docs/a.md",
        "https://docs.example.com/specification/b.md",
    ]


def test_no_url_include_means_keep_everything():
    source = _source({ROOT: "- [A](https://docs.example.com/anything/a.md)\n"})

    assert len(source.discover()) == 1


# --- version hints --------------------------------------------------------

def test_discover_leaves_version_hint_unset():
    source = _source({ROOT: "- [A](https://docs.example.com/docs/2026-07-28/a.md)\n"})

    assert source.discover()[0].version_hint is None


def test_discover_raises_on_unreachable_root():
    with pytest.raises(httpx.HTTPStatusError):
        _source({}).discover()


# --- keep_all_versions ----------------------------------------------------

def test_keep_all_versions_true_returns_every_version():
    pages = {
        ROOT: (
            "- [A old](https://docs.example.com/docs/2025-11-25/a.md)\n"
            "- [A new](https://docs.example.com/docs/2026-07-28/a.md)\n"
        )
    }

    assert len(_source(pages, keep_all_versions=True).discover()) == 2


def test_keep_all_versions_false_prunes_to_the_newest():
    pages = {
        ROOT: (
            "- [A old](https://docs.example.com/docs/2025-11-25/a.md)\n"
            "- [A new](https://docs.example.com/docs/2026-07-28/a.md)\n"
            "- [B](https://docs.example.com/community/b.md)\n"
        )
    }

    refs = _source(pages, keep_all_versions=False).discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/community/b.md",
        "https://docs.example.com/docs/2026-07-28/a.md",
    ]
