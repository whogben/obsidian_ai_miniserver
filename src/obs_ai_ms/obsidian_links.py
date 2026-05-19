"""Rewrite Obsidian wikilinks and Markdown links when a note is renamed within a vault.

Basename-only wikilinks ``[[note]]`` match the moved file when ``note`` equals the
last segment of the old path (same rule Obsidian uses for unresolved short links).
If several notes share that basename, Obsidian may pick one arbitrarily; we rewrite
every ``[[basename]]`` that matches the moved file's basename (documented limitation).
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from urllib.parse import unquote

_WIKI = re.compile(r"\[\[([^\]]+)\]\]")
# Exclude Obsidian/MD image ![alt](url) — only rewrite normal links [label](url)
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")


def normalize_rel(rel: str) -> str:
    """Vault-relative path: forward slashes, no leading slash, no .md suffix."""
    r = rel.replace("\\", "/").strip().lstrip("/")
    if r.endswith(".md"):
        return r[:-3]
    return r


def _replace_one_wiki_inner(inner: str, old_norm: str, new_norm: str) -> str:
    if "|" in inner:
        left, rest = inner.split("|", 1)
        pipe_rest = "|" + rest
    else:
        left = inner
        pipe_rest = ""
    left = left.strip()
    if "#" in left:
        path_part, frag = left.split("#", 1)
        hash_frag = "#" + frag
    else:
        path_part = left
        hash_frag = ""
    path_part = path_part.strip()
    pn = normalize_rel(path_part)
    if pn == old_norm:
        link_target = new_norm
    elif "/" not in pn and PurePosixPath(old_norm).name == pn:
        # [[basename]] → [[newbasename]] (nested notes; see module docstring)
        link_target = PurePosixPath(new_norm).name
    else:
        return inner
    return link_target + hash_frag + pipe_rest


def rewrite_wikilinks(text: str, old_rel: str, new_rel: str) -> str:
    old_norm = normalize_rel(old_rel)
    new_norm = normalize_rel(new_rel)

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        new_inner = _replace_one_wiki_inner(inner, old_norm, new_norm)
        return f"[[{new_inner}]]"

    return _WIKI.sub(repl, text)


def _resolve_md_href_to_norm(href: str, containing_rel: str) -> str | None:
    raw = href.strip()
    if not raw or raw.startswith(("http://", "https://", "mailto:", "obsidian://", "#")):
        return None
    path_part = raw.split("#")[0].split("?")[0]
    path_part = unquote(path_part).strip()
    if not path_part:
        return None
    if path_part.startswith("/"):
        rel = path_part.lstrip("/")
    else:
        src_dir = PurePosixPath(containing_rel).parent
        rel = str(src_dir / path_part)
    rel = str(PurePosixPath(rel))
    return normalize_rel(rel)


def _relative_href(from_file_rel: str, to_file_rel: str, prefer_leading_slash: bool) -> str:
    """Link target as shown in parens; to_file_rel includes .md if needed."""
    to_norm = normalize_rel(to_file_rel)
    to_with_md = f"{to_norm}.md"
    start = PurePosixPath(from_file_rel).parent
    target = PurePosixPath(to_with_md)
    rel = os.path.relpath(str(target), str(start)).replace("\\", "/")
    if prefer_leading_slash:
        return "/" + to_with_md
    return rel


def rewrite_markdown_links(
    text: str,
    old_rel: str,
    new_rel: str,
    containing_rel: str,
) -> str:
    """Rewrite [x](href) where href resolves to old_rel; paths relative to containing_rel."""
    old_norm = normalize_rel(old_rel)

    def repl(m: re.Match[str]) -> str:
        label, href = m.group(1), m.group(2)
        stripped = href.strip()
        resolved = _resolve_md_href_to_norm(stripped, containing_rel)
        if resolved is None or resolved != old_norm:
            return m.group(0)
        leading = stripped.lstrip().startswith("/")
        new_href = _relative_href(containing_rel, new_rel, leading)
        return f"[{label}]({new_href})"

    return _MD_LINK.sub(repl, text)


def rewrite_links_in_markdown(
    text: str,
    old_rel: str,
    new_rel: str,
    containing_file_rel: str,
) -> str:
    """Apply wikilink and Markdown link rewrites for a rename old_rel -> new_rel."""
    t = rewrite_wikilinks(text, old_rel, new_rel)
    return rewrite_markdown_links(t, old_rel, new_rel, containing_file_rel)
