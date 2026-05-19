"""Unit tests for Obsidian link rewriting."""

from obs_ai_ms.obsidian_links import (
    normalize_rel,
    rewrite_links_in_markdown,
    rewrite_markdown_links,
    rewrite_wikilinks,
)


def test_normalize_rel():
    assert normalize_rel("notes/a.md") == "notes/a"
    assert normalize_rel("/notes/a.md") == "notes/a"


def test_wikilink_full_path():
    t = "See [[notes/old]] and done."
    assert (
        rewrite_wikilinks(t, "notes/old.md", "notes/new.md")
        == "See [[notes/new]] and done."
    )


def test_wikilink_with_md_suffix():
    t = "[[notes/old.md]]"
    assert rewrite_wikilinks(t, "notes/old.md", "notes/new.md") == "[[notes/new]]"


def test_wikilink_heading_and_alias():
    t = "[[notes/old#hdr|label]]"
    assert (
        rewrite_wikilinks(t, "notes/old.md", "dir/new.md")
        == "[[dir/new#hdr|label]]"
    )


def test_wikilink_root_basename_only():
    t = "[[readme]] tail"
    assert rewrite_wikilinks(t, "readme.md", "intro.md") == "[[intro]] tail"


def test_wikilink_nested_basename_only():
    """[[old]] matches notes/sub/old.md; Obsidian resolves basename-style links."""
    t = "[[old]]"
    assert (
        rewrite_wikilinks(t, "notes/sub/old.md", "notes/sub/new.md") == "[[new]]"
    )


def test_markdown_relative():
    t = "Link [x](old.md)"
    assert (
        rewrite_markdown_links(t, "notes/old.md", "notes/new.md", "notes/other.md")
        == "Link [x](new.md)"
    )


def test_markdown_absolute_from_root():
    t = "Link [x](/notes/old.md)"
    assert (
        rewrite_markdown_links(t, "notes/old.md", "notes/new.md", "x.md")
        == "Link [x](/notes/new.md)"
    )


def test_markdown_skip_http():
    t = "Link [x](https://a/b/old.md)"
    assert rewrite_markdown_links(t, "notes/old.md", "notes/new.md", "z.md") == t


def test_rewrite_links_in_markdown_combined():
    t = "[[notes/a]] and [l](a.md)"
    out = rewrite_links_in_markdown(t, "notes/a.md", "notes/b.md", "notes/c.md")
    assert "[[notes/b]]" in out and "[l](b.md)" in out


def test_image_not_mangled():
    t = "![alt](notes/old.md)"
    assert rewrite_markdown_links(t, "notes/old.md", "notes/new.md", "x.md") == t
