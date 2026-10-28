#!/usr/bin/env python3
"""Record this fork's code changes as `i18n-he/code-overlay.json`, the table
`apply_code_overlay.py` replays on a fresh upstream checkout.

    python3 i18n-he/tools/record_code_overlay.py --base HEAD^2   # after a sync merge
    python3 i18n-he/tools/record_code_overlay.py --base <upstream commit>
    python3 i18n-he/tools/record_code_overlay.py --check         # is the tree still what the table says?

The base is upstream's tree *without* this fork's overlay: after a daily sync merge (whose message
names `storytold/wordcraft`) that is the merge's second parent, `HEAD^2`. Every file that differs
from it is recorded as the exact base text a change replaces — or the unique base line it goes
after — and the text it becomes. `crates/ui-egui/src/i18n.rs`'s `he` row is left out:
`apply_code_overlay.py` writes that one, so it exists on a tree that never had it.

`--check` needs no base: it verifies that every recorded change is in the tree (an inserted or
replacement block present, a replaced base text gone) and that `i18n-he/code/` still matches the
files it copies. That holds through a sync merge, where upstream's newer code sits around the
changes. Files this fork adds whole are copied to `i18n-he/code/<path>` by hand; `--check` reports
when a copy has drifted.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

# The files the Hebrew overlay edits, by their place in the tree. A file that upstream does not
# have (it was renamed or removed) is reported, so the table stops quietly rotting. The ribbon
# (`ribbon.rs`, `widgets/groups.rs`, `mini_toolbar.rs`, `ribbon/design.rs`, `widgets/combo.rs`) is
# not here: it is left exactly as upstream has it, because a mirrored ribbon piled its groups on
# top of each other (see `crates/ui-egui/src/rtl.rs`).
FILES = [
    "apps/wordcraft/src/main.rs",
    "crates/control-key/src/lib.rs",
    "crates/proof/src/hyphen.rs",
    "crates/proof/src/lang.rs",
    "crates/proof/src/lib.rs",
    "crates/ui-egui/src/app.rs",
    "crates/ui-egui/src/app/fonts.rs",
    "crates/ui-egui/src/chrome.rs",
    "crates/ui-egui/src/dialogs/chrome.rs",
    "crates/ui-egui/src/i18n.rs",
    "crates/ui-egui/src/i18n/tests.rs",
    "crates/ui-egui/src/lib.rs",
    "crates/ui-egui/src/options.rs",
    "crates/ui-egui/src/ribbon/language.rs",
    "crates/ui-egui/src/window_ui.rs",
]

# Written by `apply_code_overlay.py` itself (the Hebrew row and its comment), not recorded here.
SKIP_IN = {"crates/ui-egui/src/i18n.rs": ['code: "he"']}


def base_text(root: Path, base: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"], capture_output=True, text=True, check=True).stdout


def hunks_for(before: str, after: str, path: str) -> list[dict]:
    """Every change as a replacement (`old` → `new`) or a pure insertion (`insert` after `after`)."""
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
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
                if anchor and before.count(anchor) == 1:
                    break
            else:
                raise SystemExit(f"error: {path}: no unique line to insert after:\n{made}")
            hunks.append({"after": anchor, "insert": made})
            continue
        for n in range(0, 7):
            old_n = "".join(a[max(0, before_i - n) : before_i]) + old
            new_n = "".join(b[max(0, before_j - n) : before_j]) + made
            if before.count(old_n) == 1:
                break
        else:
            raise SystemExit(f"error: {path}: no unique text to replace:\n{old}")
        hunks.append({"old": old_n, "new": new_n})
    return hunks


def missing_from_tree(root: Path, table: dict[str, list[dict]]) -> list[str]:
    """The recorded changes that the tree does not (or does still) show, and stale copies."""
    problems: list[str] = []
    for path, hunks in table.items():
        source = (root / path).read_text(encoding="utf-8")
        for hunk in hunks:
            if "old" in hunk:
                if hunk["new"] not in source:
                    problems.append(f"{path}: misses the overlay's `{hunk['new'].strip().splitlines()[0][:60]}`")
                elif hunk["old"] in source:
                    problems.append(f"{path}: still has the text the overlay replaces: `{hunk['old'].strip().splitlines()[0][:60]}`")
            elif hunk["insert"] not in source:
                problems.append(f"{path}: misses the overlay's `{hunk['insert'].strip().splitlines()[0][:60]}`")
    code = root / "i18n-he/code"
    for copy in sorted(code.rglob("*.rs")):
        relative = copy.relative_to(code)
        target = root / relative
        if not target.exists():
            problems.append(f"{relative}: missing (copy it from {copy.relative_to(root)})")
        elif target.read_bytes() != copy.read_bytes():
            problems.append(f"{relative}: drifted from {copy.relative_to(root)}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="upstream's tree without the overlay (after a sync merge: HEAD^2)")
    parser.add_argument("--check", action="store_true", help="verify the tree still carries every recorded change")
    args = parser.parse_args()

    target = root / "i18n-he/code-overlay.json"
    if args.check:
        problems = missing_from_tree(root, json.loads(target.read_text(encoding="utf-8")))
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        if problems:
            return 1
        print("ok: the tree carries every change i18n-he/code-overlay.json records")
        return 0

    if not args.base:
        parser.error("--base is required to record: it is upstream's tree without the overlay (after a sync merge, HEAD^2)")

    table: dict[str, list[dict]] = {}
    for path in FILES:
        try:
            before = base_text(root, args.base, path)
        except subprocess.CalledProcessError:
            raise SystemExit(f"error: {args.base} has no {path}: wrong base, or upstream moved the file") from None
        table[path] = hunks_for(before, (root / path).read_text(encoding="utf-8"), path)
    # Recording against a tree that already has the overlay would produce an empty table: say so.
    if not any(table.values()):
        raise SystemExit(f"error: {args.base} already contains the overlay: pass upstream's commit, not this fork's")
    target.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"ok: {sum(len(h) for h in table.values())} change(s) in {len(table)} file(s) recorded")
    problems = missing_from_tree(root, table)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
