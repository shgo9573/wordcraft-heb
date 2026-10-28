#!/usr/bin/env python3
"""Lay out a `CRAFT_I18N_DIR` that holds craft-i18n's catalogs plus this fork's Hebrew ones.

An app embeds its interface translations from a craft-i18n checkout (`CRAFT_I18N_DIR`, see
craft-i18n's `docs/integration.md`). Hebrew is not in storytold/craft-i18n yet: it lives in this
fork, in `i18n-he/locales/he/`. This script copies the checkout's `locales/` into `--out` and
overlays the Hebrew files on top, so the build embeds both:

    python3 i18n-he/tools/assemble.py --craft-i18n ../craft-i18n --out target/craft-i18n-he
    export CRAFT_I18N_DIR=$PWD/target/craft-i18n-he CRAFT_I18N_REQUIRED=1
    cargo build --release

Without `--craft-i18n` (or with a directory that is not a checkout) it lays out the Hebrew
catalogs alone: the interface is then English plus Hebrew, which is enough for development.
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
    if args.craft_i18n:
        base = copy_locales(args.craft_i18n / "locales", args.out)
        if base == 0:
            print(f"warning: {args.craft_i18n} has no locales/, so only the overlay is embedded", file=sys.stderr)
    else:
        print("note: no --craft-i18n, so only the overlay is embedded (English plus its locales)", file=sys.stderr)
    overlaid = copy_locales(args.overlay, args.out)

    if not (args.out / "locales" / "he" / "wordcraft.tsv").exists():
        print(f"the overlay has no he/wordcraft.tsv: {args.overlay}", file=sys.stderr)
        return 1
    print(f"{args.out}: {base} craft-i18n locale(s) plus {overlaid} overlay locale(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
