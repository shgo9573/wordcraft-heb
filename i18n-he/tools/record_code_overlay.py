#!/usr/bin/env python3
"""Record this fork's code changes as `i18n-he/code-overlay.json`, the table
`apply_code_overlay.py` replays on a fresh upstream checkout.

    python3 i18n-he/tools/record_code_overlay.py            # write the table
    python3 i18n-he/tools/record_code_overlay.py --check    # fail if it is stale
    python3 i18n-he/tools/record_code_overlay.py --base origin/main

The base is the commit upstream last merged into (`HEAD` by default, since a merge commit of this
fork is upstream's tree plus the overlay): every file that differs from it is recorded as the exact
base text a change replaces — or the unique base line it goes after — and the text it becomes.
`crates/ui-egui/src/i18n.rs`'s `he` row is left out: `apply_code_overlay.py` writes that one, so it
exists on a tree that never had it.

Files this fork adds whole are copied to `i18n-he/code/<path>` and are not part of the table.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

# The files the Hebrew overlay edits, by their place in the tree. A file that upstream does not
# have (it was renamed or removed) is reported, so the table stops quietly rotting.
FILES = [
    "crates/proof/src/hyphen.rs",
    "crates/proof/src/lang.rs",
    "crates/proof/src/lib.rs",
    "crates/ui-egui/src/app/fonts.rs",
    "crates/ui-egui/src/chrome.rs",
    "crates/ui-egui/src/dialogs/chrome.rs",
    "crates/ui-egui/src/i18n.rs",
    "crates/ui-egui/src/i18n/tests.rs",
    "crates/ui-egui/src/lib.rs",
    "crates/ui-egui/src/mini_toolbar.rs",
    "crates/ui-egui/src/options.rs",
    "crates/ui-egui/src/ribbon.rs",
    "crates/ui-egui/src/ribbon/design.rs",
    "crates/ui-egui/src/ribbon/language.rs",
    "crates/ui-egui/src/widgets/combo.rs",
    "crates/ui-egui/src/widgets/groups.rs",
]

# Written by `apply_code_overlay.py` itself (the Hebrew row and its comment), not recorded here.
SKIP_IN = {"crates/ui-egui/src/i18n.rs": ['code: "he"']}


def base_text(root: Path, base: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"], capture_output=True, text=True, check=True).stdout


def hunks_for(bytes_old: str, new: str, path: str) -> list[dict]:
    """Every change as a replacement (`old` → `new`) or a pure insertion (`insert` after `after`)."""
    a, b = bytes_old.splitlines(keepends=True), new.splitlines(keepends=True)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    skips = SKIP_IN.get(path, [])
    hunks: list[dict] = []
    for index, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        old, made = "".join(a[i1:i2]), "".join(b[j1:j2])
        if any(marker in old for marker in skips):
            continue
        previous = [op for op in ops[:index] if op[0] == "equal"]
        before_i, before_j = (previous[-1][2], previous[-1][4]) if previous else (0, 0)
        if not old.strip():
            for n in range(1, 7):
                anchor = "".join(a[max(0, before_i - n) : before_i])
                if anchor and bytes_old.count(anchor) == 1:
                    break
            else:
                raise SystemExit(f"error: {path}: no unique line to insert after:\n{made}")
            hunks.append({"after": anchor, "insert": made})
            continue
        for n in range(0, 7):
            old_n = "".join(a[max(0, before_i - n) : before_i]) + old
            new_n = "".join(b[max(0, before_j - n) : before_j]) + made
            if bytes_old.count(old_n) == 1:
                break
        else:
            raise SystemExit(f"error: {path}: no unique text to replace:\n{old}")
        hunks.append({"old": old_n, "new": new_n})
    return hunks


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="HEAD", help="the commit to compare with (default HEAD)")
    parser.add_argument("--check", action="store_true", help="only compare with the recorded table")
    args = parser.parse_args()

    table: dict[str, list[dict]] = {}
    for path in FILES:
        new = (root / path).read_text(encoding="utf-8")
        table[path] = hunks_for(base_text(root, args.base, path), new, path)
    recorded = json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True)
    target = root / "i18n-he/code-overlay.json"
    if args.check:
        current = json.dumps(json.loads(target.read_text(encoding="utf-8")), ensure_ascii=False, indent=1, sort_keys=True)
        if current != recorded:
            print("error: i18n-he/code-overlay.json is stale: run i18n-he/tools/record_code_overlay.py", file=sys.stderr)
            return 1
        print("ok: i18n-he/code-overlay.json matches the tree")
        return 0
    target.write_text(recorded, encoding="utf-8", newline="\n")
    print(f"ok: {sum(len(h) for h in table.values())} change(s) in {len(table)} file(s) recorded")
    # The copies of the files this fork adds whole.
    code = root / "i18n-he/code"
    added = 0
    for source in sorted(code.rglob("*.rs")):
        relative = source.relative_to(code)
        if (root / relative).read_bytes() != source.read_bytes():
            print(f"error: {relative}: i18n-he/code/ is stale: copy it from {relative}", file=sys.stderr)
            added += 1
    return 1 if added else 0


if __name__ == "__main__":
    sys.exit(main())
