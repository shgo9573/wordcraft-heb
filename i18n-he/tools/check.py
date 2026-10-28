#!/usr/bin/env python3
"""Check the Hebrew catalogs in `i18n-he/locales/` against craft-i18n's catalog rules.

craft-i18n (`docs/catalog-format.md`) checks every catalog it ships; these files live in this
fork instead, so this script applies the same rules here, and adds the two this fork needs: the
clean-room header and no row equal to a shared row of the same locale.

    python3 i18n-he/tools/check.py                        # the catalogs alone
    python3 i18n-he/tools/check.py --craft-i18n ../craft-i18n
                                                          # also report stale rows and coverage

Every rule failure exits 1 with one line per problem. A partial catalog is fine: rows that are
missing simply show their English text, and `--craft-i18n` prints how many there are.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
ESCAPES = re.compile(r"\\(.)")
ALLOWED_ESCAPES = {"n", "t", "\\"}
KNOWN_CONTEXTS = {"@plural", "@id", "@msg"}
# CLDR cardinal categories Hebrew reaches for whole numbers 0..1000: one, two, many, other.
HEBREW_PLURAL_FORMS = 4
HEADER_MARKER = "Clean room:"


def read_catalog(path: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(context, source, translation) rows and the problems found reading them."""
    rows: list[tuple[str, str, str]] = []
    problems: list[str] = []
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if HEADER_MARKER not in text:
        problems.append(f"{path.name}: the header has no `{HEADER_MARKER}` line")
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        where = f"{path.name}:{number}"
        fields = line.split("\t")
        if len(fields) != 3:
            problems.append(f"{where}: {len(fields)} tab-separated columns, want 3")
            continue
        context, source, translation = fields
        if context and not context.startswith("@"):
            # A plain context is a label telling two meanings apart; the apps fall back to the
            # plain row, so such a row is legal and nothing more is checked about it.
            pass
        elif context and context not in KNOWN_CONTEXTS:
            problems.append(f"{where}: unknown context `{context}`")
        if not source:
            problems.append(f"{where}: an empty source text (the English is the key)")
        if not translation.strip():
            problems.append(f"{where}: an empty translation")
        for column, value in (("source", source), ("translation", translation)):
            for escape in ESCAPES.findall(value):
                if escape not in ALLOWED_ESCAPES:
                    problems.append(f"{where}: `\\{escape}` in the {column} is not an escape")
        rows.append((context, source, translation))
    return rows, problems


def check_row(where: str, context: str, source: str, translation: str) -> list[str]:
    """Placeholders, ellipses and plural forms — the rules craft-i18n enforces."""
    problems: list[str] = []
    if context == "@plural":
        source_forms = source.split("|")
        forms = translation.split("|")
        if len(forms) != HEBREW_PLURAL_FORMS:
            problems.append(f"{where}: {len(forms)} plural forms, Hebrew needs {HEBREW_PLURAL_FORMS} (one|two|many|other)")
        names: set[str] = set()
        for part in source_forms + forms:
            names |= set(PLACEHOLDER.findall(part))
        for part in forms:
            if set(PLACEHOLDER.findall(part)) != set(PLACEHOLDER.findall(source_forms[0])):
                problems.append(f"{where}: plural form `{part}` has different placeholders than `{source_forms[0]}`")
            if part.endswith("…") != source_forms[0].endswith("…"):
                problems.append(f"{where}: plural form `{part}` and `{source_forms[0]}` disagree about the trailing ellipsis")
        del names
        return problems
    wanted = set(PLACEHOLDER.findall(source))
    got = set(PLACEHOLDER.findall(translation))
    if wanted != got:
        problems.append(f"{where}: placeholders {sorted(wanted)} in the English, {sorted(got)} in the Hebrew")
    if source.endswith("…") != translation.endswith("…"):
        problems.append(f"{where}: the English and the Hebrew disagree about the trailing ellipsis")
    return problems


def english_keys(craft_i18n: Path) -> dict[str, dict[str, set[str]]]:
    """`{catalog: {context: {source}}}` for the English side (read from the German catalogs,
    the largest of the shipped translations, which hold the same keys)."""
    keys: dict[str, dict[str, set[str]]] = {}
    for catalog in ("common", "wordcraft"):
        path = craft_i18n / "locales" / "de" / f"{catalog}.tsv"
        if not path.exists():
            continue
        found: dict[str, set[str]] = {}
        for line in path.read_text(encoding="utf-8").split("\n"):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) == 3:
                found.setdefault(fields[0], set()).add(fields[1])
        keys[catalog] = found
    return keys


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--locales", type=Path, default=root / "i18n-he" / "locales", help="the overlay's locales/ (default: i18n-he/locales)")
    parser.add_argument("--craft-i18n", type=Path, help="a storytold/craft-i18n checkout, for the key list and the coverage report")
    args = parser.parse_args()

    catalogs = sorted(args.locales.glob("*/[a-z]*.tsv"))
    if not catalogs:
        print(f"no catalogs under {args.locales}", file=sys.stderr)
        return 1

    problems: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    app_rows: dict[str, dict[tuple[str, str], str]] = {}
    shared_rows: dict[str, dict[tuple[str, str], str]] = {}
    for path in catalogs:
        locale, catalog = path.parent.name, path.stem
        rows, read_problems = read_catalog(path)
        problems += read_problems
        seen: set[tuple[str, str]] = set()
        for number, (context, source, translation) in enumerate(rows, start=1):
            key = (context, source)
            if key in seen:
                problems.append(f"{path.name}: `{source}` (context `{context}`) appears twice")
            seen.add(key)
            problems += check_row(f"{path.name}: `{source}`", context, source, translation)
            if catalog == "common":
                shared_rows.setdefault(locale, {})[key] = translation
            else:
                app_rows.setdefault(locale, {})[key] = translation
        counts.setdefault(locale, {})[catalog] = len(rows)

    for locale, rows in app_rows.items():
        shared = shared_rows.get(locale, {})
        for key, translation in rows.items():
            if shared.get(key) == translation:
                problems.append(f"{locale}/{key[1]}: the app row repeats the shared row, so it changes nothing")

    if ("@id", "language.name") not in shared_rows.get("he", {}):
        problems.append("he/common.tsv: no `@id\tlanguage.name` row, so the language picker shows the code")

    if args.craft_i18n:
        keys = english_keys(args.craft_i18n)
        for locale, catalogs_here in sorted(counts.items()):
            for catalog, count in sorted(catalogs_here.items()):
                known = set().union(*keys.get(catalog, {}).values()) if keys.get(catalog) else set()
                if not known:
                    continue
                ours = app_rows.get(locale, {}) if catalog != "common" else shared_rows.get(locale, {})
                stale = sorted({key[1] for key in ours} - known)
                if stale:
                    print(f"{locale}/{catalog}.tsv: {len(stale)} row(s) the app no longer asks for (harmless): {', '.join(stale[:8])}{' …' if len(stale) > 8 else ''}")
                total = len(known)
                print(f"{locale}/{catalog}.tsv: {count} rows, {count * 100 // max(total, 1)}% of the {total} English strings")

    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    summary = ", ".join(f"{locale}/{catalog}: {count}" for locale, catalogs_here in sorted(counts.items()) for catalog, count in sorted(catalogs_here.items()))
    print(f"ok: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
