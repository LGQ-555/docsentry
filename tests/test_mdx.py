"""MDX container normalisation -- design spec 6.2.1.

The corpus is Mintlify-flavoured MDX: tabbed content is indented inside
<Tabs>/<Tab>/<CodeGroup>, and CommonMark reads indented content as a *code
block*. Measured on the real corpus: 1,235,578 characters (8.5%) arrive
misparsed, and `build-client.md` shows the parser only 2 of its 127 headings.
"""

from docsentry.corpus.mdx import normalise, scan


def test_scan_finds_nested_container_indents():
    text = (
        "<Tabs>\n"
        '  <Tab title="Python">\n'
        "    ## Requirements\n"
        "\n"
        "    <CodeGroup>\n"
        "      ```bash\n"
        "      uv venv\n"
        "      ```\n"
        "    </CodeGroup>\n"
        "  </Tab>\n"
        "</Tabs>\n"
    )
    frames, owner, kind = scan(text.splitlines(keepends=True))

    layout = [f for f in frames if f.tag in ("Tabs", "Tab", "CodeGroup")]
    assert [f.tag for f in layout] == ["Tabs", "Tab", "CodeGroup"]
    # each level adds 2: <Tabs> content at 2, <Tab> content at 4, <CodeGroup> at 6
    assert [f.min_indent for f in layout] == [2, 4, 6]
    assert layout[1].title == "Python"
    assert layout[0].title is None


def test_scan_ignores_tag_lookalikes_inside_fences():
    text = (
        "```html\n"
        "<Tabs>\n"
        "</Tabs>\n"
        "```\n"
    )
    frames, _owner, _kind = scan(text.splitlines(keepends=True))
    assert frames == []


def test_scan_assigns_each_content_line_to_its_innermost_container():
    text = (
        "<Tabs>\n"
        '  <Tab title="Python">\n'
        "    ## Requirements\n"
        "  </Tab>\n"
        "</Tabs>\n"
        "outside\n"
    )
    _frames, owner, kind = scan(text.splitlines(keepends=True))
    lines = text.splitlines(keepends=True)
    idx = {line.strip(): i for i, line in enumerate(lines)}

    assert owner[idx["## Requirements"]].tag == "Tab"
    assert owner[idx["outside"]] is None
    assert kind[idx["## Requirements"]] == "content"
    assert kind[idx["<Tabs>"]] == "open"
    assert kind[idx["</Tabs>"]] == "close"


def test_normalise_removes_tags_and_dedents_content():
    text = (
        "<Tabs>\n"
        '  <Tab title="Python">\n'
        "    ## Requirements\n"
        "\n"
        "    Needs Python 3.10.\n"
        "  </Tab>\n"
        "</Tabs>\n"
    )
    out = normalise(text)
    assert "<Tabs>" not in out and "<Tab" not in out
    assert "## Requirements" in out
    assert "\n    Needs Python 3.10." not in out   # dedented to column 0


def test_normalise_keeps_fenced_code_fenced():
    """The trap: a fence inside a container is indented too. If only the
    surrounding prose is dedented the fence stays indented, or if the tags are
    left in place they open an HTML block that swallows it -- either way a
    shell comment like `# Create virtual environment` is promoted to an H1."""
    text = (
        "<Tabs>\n"
        '  <Tab title="Python">\n'
        "    <CodeGroup>\n"
        "      ```bash\n"
        "      # Create virtual environment\n"
        "      uv venv\n"
        "      ```\n"
        "    </CodeGroup>\n"
        "  </Tab>\n"
        "</Tabs>\n"
    )
    out = normalise(text)

    from markdown_it import MarkdownIt

    tokens = MarkdownIt("commonmark").parse(out)
    headings = [tokens[k + 1].content
                for k, t in enumerate(tokens) if t.type == "heading_open"]
    assert "Create virtual environment" not in headings
    assert any(t.type == "fence" for t in tokens)
    assert "uv venv" in next(t.content for t in tokens if t.type == "fence")


def test_normalise_drops_semantic_wrappers_but_keeps_text():
    text = "<Note>\n  Check your API key.\n</Note>\n"
    out = normalise(text)
    assert "<Note>" not in out
    assert "Check your API key." in out
