#!/usr/bin/env python3
"""Lay out a `CRAFT_I18N_DIR` that holds craft-i18n's catalogs plus this fork's Hebrew ones.

An app embeds its interface translations from a craft-i18n checkout (`CRAFT_I18N_DIR`, see
craft-i18n's `docs/integration.md`). This fork's Hebrew lives in `i18n-he/locales/he/`; craft-i18n
has a Hebrew catalog of its own too, so the two are merged — this fork's translation wins for a
string it has, craft-i18n's row stays for every string it does not, and nothing falls back to
English that either of them translated. This script copies the checkout's `locales/` **and its
`language-data/`** into `--out` and lays the Hebrew files over them, so the build embeds both:

    python3 i18n-he/tools/assemble.py --craft-i18n ../craft-i18n --out target/craft-i18n-he
    export CRAFT_I18N_DIR=$PWD/target/craft-i18n-he CRAFT_I18N_REQUIRED=1
    cargo build --release

`language-data/` is not a catalog and is copied as it is: craft-proof (craft-libs) embeds the
spelling word lists and hyphenation patterns from `$CRAFT_I18N_DIR/language-data` at build time, and
a `CRAFT_I18N_DIR` without it stops a `CRAFT_I18N_REQUIRED=1` build with "has no language-data/".
Hebrew needs no Language data of its own — its dictionary is the system's `he_IL` (see
`crates/proof-he`) — so the checkout's data is complete as it is.

Without `--craft-i18n` (or with a directory that is not a checkout) it lays out the Hebrew
catalogs alone: the interface is then English plus Hebrew, which is enough for development (and
such a build embeds no Language data, which craft-proof warns about).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def copy_locales(locales: Path, out: Path) -> int:
    """Copy the locale directories under `locales` into `out/locales`; returns how many there were."""
    if not locales.is_dir():
        return 0
    copied = 0
    for locale in sorted(p for p in locales.iterdir() if p.is_dir()):
        target = out / "locales" / locale.name
        target.mkdir(parents=True, exist_ok=True)
        for file in sorted(locale.glob("*.tsv")):
            shutil.copyfile(file, target / file.name)
        copied += 1
    return copied


def merge_catalogs(base: Path, overlay: Path, target: Path) -> int:
    """Write `overlay`'s rows over `base`'s, key by key; returns how many rows the file has.

    craft-i18n ships its own Hebrew now (it did not when this fork's overlay was written). A plain
    copy would replace its 2,600 rows with this fork's 1,480 and show the difference in English, so
    the two are merged: for the same (context, English) pair this fork's translation wins — that is
    where its Word vocabulary lives — and every other row of craft-i18n's stays. The rows are written
    sorted by English text, as the catalogs here are.
    """
    header: list[str] = []
    rows: dict[tuple[str, str], str] = {}
    for file in (base, overlay):
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if line.startswith("#"):
                if file is overlay:
                    header.append(line)
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            rows[(parts[0], parts[1])] = line
    body = [rows[key] for key in sorted(rows, key=lambda k: (k[1].lower(), k[0]))]
    target.write_text("\n".join(header + body) + "\n", encoding="utf-8", newline="\n")
    return len(body)


def overlay_locales(overlay: Path, out: Path, craft_i18n: Path | None) -> tuple[int, int]:
    """Copy the overlay's locale files into `out`; a file craft-i18n has too is merged.

    Returns the number of overlay locales laid out, and of files merged rather than copied. A
    plain copy would replace craft-i18n's Hebrew, which has the rows this fork has not reached yet.
    """
    locales = merged = 0
    for locale in sorted(p for p in overlay.iterdir() if p.is_dir()):
        target_dir = out / "locales" / locale.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for file in sorted(locale.glob("*.tsv")):
            target = target_dir / file.name
            theirs = craft_i18n / "locales" / locale.name / file.name if craft_i18n else None
            if theirs is not None and theirs.is_file():
                rows = merge_catalogs(theirs, file, target)
                print(f"{locale.name}/{file.name}: {rows} row(s) after the merge with craft-i18n's")
                merged += 1
            else:
                shutil.copyfile(file, target)
        locales += 1
    return locales, merged


def copy_language_data(data: Path, out: Path) -> int:
    """Copy the checkout's `language-data/` (craft-proof's word lists and patterns); returns the
    number of files copied, 0 when the checkout has none."""
    if not data.is_dir():
        return 0
    copied = 0
    for file in sorted(p for p in data.rglob("*") if p.is_file()):
        target = out / "language-data" / file.relative_to(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        copied += 1
    return copied


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--craft-i18n", type=Path, help="a storytold/craft-i18n checkout (its locales/ is the base)")
    parser.add_argument("--overlay", type=Path, default=root / "i18n-he" / "locales", help="the locale overlay (default: i18n-he/locales)")
    parser.add_argument("--out", type=Path, required=True, help="where to lay out the catalogs")
    parser.add_argument("--keep", action="store_true", help="keep an existing --out instead of replacing it")
    args = parser.parse_args()

    if not args.overlay.is_dir():
        print(f"no overlay at {args.overlay}", file=sys.stderr)
        return 1
    if args.out.exists() and not args.keep:
        shutil.rmtree(args.out)
    (args.out / "locales").mkdir(parents=True, exist_ok=True)

    base = 0
    data = 0
    if args.craft_i18n:
        base = copy_locales(args.craft_i18n / "locales", args.out)
        if base == 0:
            print(f"warning: {args.craft_i18n} has no locales/, so only the overlay is embedded", file=sys.stderr)
        # craft-proof embeds its Language data from here (`$CRAFT_I18N_DIR/language-data`), and a
        # checkout without it stops a required build.
        data = copy_language_data(args.craft_i18n / "language-data", args.out)
        if data == 0:
            message = f"warning: {args.craft_i18n} has no language-data/, so craft-proof embeds no Language data"
            print(message, file=sys.stderr)
    else:
        print("note: no --craft-i18n, so only the overlay is embedded (English plus its locales)", file=sys.stderr)
    # A locale craft-i18n already has is merged rather than replaced: its rows for the strings this
    # fork has not reached would otherwise fall back to English.
    overlaid, merged = overlay_locales(args.overlay, args.out, args.craft_i18n if base else None)

    if not (args.out / "locales" / "he" / "wordcraft.tsv").exists():
        print(f"the overlay has no he/wordcraft.tsv: {args.overlay}", file=sys.stderr)
        return 1
    print(f"{args.out}: {base} craft-i18n locale(s) plus {overlaid} overlay locale(s) ({merged} merged), {data} language-data file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
