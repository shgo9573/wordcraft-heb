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
CODE_TOKEN = re.compile(r'r#*"(?:[^"]|"(?!#))*"#*|"(?:[^"\\\n]|\\.)*"|\w+|\S')


def code_pattern(text: str) -> re.Pattern[str]:
    """`text` as a pattern that finds the same code however it is wrapped and indented."""
    return re.compile(r"\s*".join(re.escape(token) for token in CODE_TOKEN.findall(text)))


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
    return CODE_TOKEN.findall(left) == CODE_TOKEN.findall(right)
