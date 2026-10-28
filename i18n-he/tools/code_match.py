"""Finding the code an overlay hunk records, in a tree whose whitespace `cargo fmt` moved.

A hunk in `i18n-he/code-overlay.json` is upstream's text and the text this fork makes of it. Neither
is stable as a *string*: the workflow merges upstream and then formats the result (`cargo fmt
--all`), and the format is what `main` carries, so the next run finds `ui` and `.add_sized(...)` on
separate lines where the hunk has `ui.add_sized(...)`. That difference is not a change: the code is
the same. So both sides are compared by their tokens — a string, a word, or a single character —
and whitespace *between* tokens counts for nothing.
"""

from __future__ import annotations

import re

# What `cargo fmt` never breaks apart: a raw string, a string, a word, or one other character.
# How much of an inserted block says it is there: its first tokens.
INSERT_MARKER = 12

CODE_TOKEN = re.compile(r'r#*"(?:[^"]|"(?!#))*"#*|"(?:[^"\\\n]|\\.)*"|\w+|\S')


def tokens(text: str) -> list[str]:
    return CODE_TOKEN.findall(text)


def code_pattern(text: str) -> re.Pattern[str]:
    """`text` as a pattern that finds the same code however it is wrapped and indented."""
    return re.compile(r"\s*".join(re.escape(token) for token in tokens(text)))


def code_matches(source: str, text: str) -> list[re.Match[str]]:
    """Where `source` has the code in `text`: empty if it does not, more than one if it is ambiguous."""
    if not CODE_TOKEN.search(text):
        return []
    return list(code_pattern(text).finditer(source))


def has_code(source: str, text: str) -> bool:
    """Does `source` have the code in `text`? (Whitespace between the tokens does not count.)"""
    return bool(code_matches(source, text))


def same_code(left: str, right: str) -> bool:
    """Are these the same code, formatted differently?"""
    return tokens(left) == tokens(right)


def whole_line(source: str, span: tuple[int, int]) -> bool:
    """Does `span` start a line and end one?"""
    start, end = span
    starts_line = start == 0 or source[start - 1] == "\n"
    ends_line = end == len(source) or source[end] == "\n"
    return starts_line and ends_line


def candidates(source: str, text: str, anchor: bool = False) -> list[tuple[int, int]]:
    """Every place `source` could have `text`: the exact text first, else the code, however wrapped.

    An anchor (the line a hunk inserts after) has to be a whole line or lines when it is matched as
    code: without its indentation a short one (`}`, a blank line) would be found everywhere.
    """
    exact = [match.span() for match in re.finditer(re.escape(text), source)]
    if exact:
        return exact
    spans = [match.span() for match in code_matches(source, text)]
    return [span for span in spans if whole_line(source, span)] if anchor else spans


def applied(source: str, hunk: dict) -> bool:
    """Is this hunk already in `source`?

    An insertion is where it goes — right after its anchor — because a short one (a lone `}`) is
    everywhere. A replacement is applied when its new code is there. A deletion, which leaves
    nothing to look for, when the code it removes is gone.
    """
    if "insert" in hunk:
        # The block's first tokens, right after the anchor: a later hunk may edit a word inside the
        # block (or a person may), and that must not make it insert twice. Enough of them to tell a
        # lone `}` from a block that happens to start with one.
        first = tokens(hunk["insert"])[:INSERT_MARKER]
        where = candidates(source, hunk["after"], anchor=True)
        if not where:
            # The line it goes after is gone (a later hunk, or upstream): the hunk counts as
            # applied when the block it inserts is somewhere in the file.
            return has_code(source, hunk["insert"])
        return any(tokens(source[end:])[: len(first)] == first for _, end in where)
    if not hunk["new"]:
        return not has_code(source, hunk["old"])
    return has_code(source, hunk["new"])
