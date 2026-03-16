"""Tests for markdown → Discord markdown conversion."""
from cogos.io.discord.markdown import convert_markdown


def test_h1_to_bold():
    assert convert_markdown("# Hello") == "**Hello**"


def test_h2_to_bold():
    assert convert_markdown("## Section") == "**Section**"


def test_h3_to_bold():
    assert convert_markdown("### Subsection") == "**Subsection**"


def test_link_to_text_url():
    assert convert_markdown("[click here](https://example.com)") == "click here (<https://example.com>)"


def test_image_to_text_url():
    assert convert_markdown("![alt text](https://example.com/img.png)") == "alt text: <https://example.com/img.png>"


def test_horizontal_rule():
    result = convert_markdown("---")
    assert "─" in result


def test_table_to_code_block():
    md = "| Name | Value |\n|------|-------|\n| foo  | bar   |"
    result = convert_markdown(md)
    assert result.startswith("```\n")
    assert result.endswith("\n```")
    assert "foo" in result


def test_passthrough_bold():
    assert convert_markdown("**bold**") == "**bold**"


def test_passthrough_italic():
    assert convert_markdown("*italic*") == "*italic*"


def test_passthrough_code_inline():
    assert convert_markdown("`code`") == "`code`"


def test_passthrough_code_block():
    md = "```python\nprint('hi')\n```"
    assert convert_markdown(md) == md


def test_passthrough_list():
    md = "- item 1\n- item 2"
    assert convert_markdown(md) == md


def test_passthrough_quote():
    md = "> quoted text"
    assert convert_markdown(md) == md


def test_mixed_content():
    md = "# Title\n\nSome **bold** text.\n\n[link](https://x.com)\n\n- item"
    result = convert_markdown(md)
    assert result.startswith("**Title**")
    assert "**bold**" in result
    assert "link (<https://x.com>)" in result
    assert "- item" in result


def test_heading_inside_code_block_not_converted():
    md = "```\n# this is a comment\n```"
    result = convert_markdown(md)
    assert "# this is a comment" in result
    assert "**this is a comment**" not in result


def test_link_inside_code_block_not_converted():
    md = "```\n[not a link](url)\n```"
    result = convert_markdown(md)
    assert "[not a link](url)" in result
