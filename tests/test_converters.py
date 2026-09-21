from pathlib import Path

from docsentry.corpus.converters.base import ConvertedDoc, Converter
from docsentry.corpus.converters.markdown import MarkdownConverter, first_heading, strip_index_banner

BANNER = (
    "> ## Documentation Index\n"
    "> Fetch the complete documentation index at: https://example.com/llms.txt\n"
    "> Use this file to discover all available pages before exploring further.\n"
    "\n"
)


# --- strip_index_banner ---------------------------------------------------

def test_strips_the_real_banner():
    assert strip_index_banner(BANNER + "# Build a server\n") == "# Build a server\n"


def test_leaves_text_without_a_banner_alone():
    assert strip_index_banner("# Title\nbody\n") == "# Title\nbody\n"


def test_keeps_a_genuine_leading_blockquote():
    text = "> **Note:** this is real content.\n\n# Title\n"

    assert strip_index_banner(text) == text


def test_strips_banner_before_a_leading_blockquote_of_real_content():
    text = BANNER + "> **Note:** real content.\n\n# Title\n"

    assert strip_index_banner(text).startswith("> **Note:**")


def test_banner_in_the_middle_is_untouched():
    text = "# Title\n\n" + BANNER

    assert strip_index_banner(text) == text


def test_handles_file_that_is_only_a_banner():
    assert strip_index_banner(BANNER) == ""


# --- first_heading --------------------------------------------------------

def test_first_heading_finds_atx_heading():
    assert first_heading("# Build an MCP server\n\nbody\n") == "Build an MCP server"


def test_first_heading_returns_empty_when_absent():
    assert first_heading("just prose\n") == ""


def test_first_heading_skips_headings_inside_code_fences():
    text = "```\n# not a title\n```\n\n# Real Title\n"

    assert first_heading(text) == "Real Title"


def test_first_heading_handles_tilde_fences():
    text = "~~~\n# not a title\n~~~\n\n# Real Title\n"

    assert first_heading(text) == "Real Title"


# --- MarkdownConverter ----------------------------------------------------

def test_converter_reports_supported_extensions():
    assert MarkdownConverter().supported == {".md", ".markdown"}


def test_converter_reads_and_normalizes(tmp_path):
    path = tmp_path / "a.md"
    path.write_text(BANNER + "# Build a server\n\nbody\n", encoding="utf-8")

    result = MarkdownConverter().convert(path)

    assert result == ConvertedDoc(
        text="# Build a server\n\nbody\n",
        title="Build a server",
        origin_format="md",
    )


def test_converter_sets_origin_format_from_suffix(tmp_path):
    path = tmp_path / "a.markdown"
    path.write_text("# A\n", encoding="utf-8")

    assert MarkdownConverter().convert(path).origin_format == "md"


def test_converter_survives_undecodable_bytes(tmp_path):
    path = tmp_path / "a.md"
    path.write_bytes(b"# A\n\xff\xfe broken\n")

    assert MarkdownConverter().convert(path).title == "A"


def test_markdown_converter_satisfies_protocol():
    assert isinstance(MarkdownConverter(), Converter)
