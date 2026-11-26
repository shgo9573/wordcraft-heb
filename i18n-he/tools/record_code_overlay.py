#!/usr/bin/env python3
"""Record this fork's code changes as `i18n-he/code-overlay.json`, the table
`apply_code_overlay.py` replays on a fresh upstream checkout.

    python3 i18n-he/tools/record_code_overlay.py --base HEAD^2   # after a sync merge
    python3 i18n-he/tools/record_code_overlay.py --base <upstream commit>
    python3 i18n-he/tools/record_code_overlay.py --check         # is the tree still what the table says?
    python3 i18n-he/tools/record_code_overlay.py --prune         # drop the changes a merge made stale

The base is upstream's tree *without* this fork's overlay: after a daily sync merge (whose message
names `storytold/wordcraft`) that is the merge's second parent, `HEAD^2`. Every file that differs
from it is recorded as the exact base text a change replaces — or the unique base line it goes
after — and the text it becomes. `crates/ui-egui/src/i18n.rs`'s `he` row is left out:
`apply_code_overlay.py` writes that one, so it exists on a tree that never had it.

`--prune` is for a sync merge, before the overlay runs: a change whose base text the merge took
away (upstream moved the code, or does the thing itself now) can never land again, so it is dropped
from the table and said in the log — the pruning commit is the merge's own, and the catalogs job's
`--check` then passes. What still applies stays exactly as it was.

A table entry may say which layout of the UI it is written for (`"layouts": ["prefs"]` after
upstream #7101, `["ui_state"]` before, nothing for both): the tools pick the hunks that fit the tree
in front of them, so one table serves a sync across the change.

`--check` needs no base: it verifies that every recorded change is in the tree (an inserted or
replacement block present, a replaced base text gone) and that `i18n-he/code/` still matches the
files it copies — this fork's Hebrew proofer, `crates/proof-he/`, whose sources and manifest are
copied there by hand; `--check` reports when a copy has drifted.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from code_match import applied, has_code, same_code  # noqa: E402  (the sibling tool's matcher)
from apply_code_overlay import apply_hunks, for_layout, has_legacy_layout  # noqa: E402

# The files the Hebrew overlay edits, by their place in the tree. A file that upstream does not
# have (it was renamed or removed) is reported, so the table stops quietly rotting.
#
# Deliberately short. Upstream mirrors a right-to-left interface itself now (`crates/ui-egui/src/rtl.rs`
# and its `he`-less `RTL_LANGUAGES`): Hebrew is one entry in that list here, and the ribbon, the
# dialogs, the grids and the combo boxes need no change of ours. What is left is this fork's own
# work — the Hebrew interface language and its default, the interface faces for a Hebrew UI, the
# Hebrew font list, and this fork's Hebrew proofer (`crates/proof-he/`, added whole below) — plus
# the handful of rows inside the ribbon that a mirror does not fix (an alignment row whose icons
# face the text).
#
# The `Cargo.toml` files are here because the proofer is a crate of its own: its membership and its
# three dependents' dependencies come from the table too, or upstream's next edit to those lines
# would break the merge.
FILES = [
    "Cargo.toml",
    "apps/wordcraft/src/main.rs",
    "crates/control-key/src/lib.rs",
    "crates/engine/Cargo.toml",
    "crates/engine/src/cmd/review/proofing.rs",
    "crates/engine/src/packs.rs",
    "crates/layout/Cargo.toml",
    "crates/layout/src/para/proof.rs",
    "crates/ui-egui/Cargo.toml",
    "crates/ui-egui/src/app.rs",
    "crates/ui-egui/src/app/commands.rs",
    "crates/ui-egui/src/app/fonts.rs",
    "crates/ui-egui/src/i18n.rs",
    "crates/ui-egui/src/i18n/tests.rs",
    "crates/ui-egui/src/panes/tests.rs",
    "crates/ui-egui/src/lib.rs",
    "crates/ui-egui/src/mini_toolbar.rs",
    "crates/ui-egui/src/previews.rs",
    "crates/ui-egui/src/previews/tests.rs",
    "crates/ui-egui/src/ribbon/design.rs",
    "crates/ui-egui/src/ribbon/home.rs",
    "crates/ui-egui/src/ribbon/language.rs",
    "crates/ui-egui/src/ribbon/tests.rs",
    "crates/ui-egui/src/widgets.rs",
    "crates/ui-egui/src/window_ui.rs",
    # The `Prefs` layout: the settings struct and the function that loads one (`apply_prefs`).
    "crates/ui-egui/src/prefs.rs",
    "crates/ui-egui/src/app/prefs.rs",
]

# Written by `apply_code_overlay.py` itself (`apply_i18n`: the Hebrew row and its comment, the
# `LANGUAGES` count that row raises, and the public `catalog_texts`), not recorded here: those are
# the changes that must survive the count moving under them, which happens whenever upstream adds a
# language of its own — a recorded `[LangInfo; 28]` would then find nothing to replace.
SKIP_IN = {
    # `apply_code_overlay.py` writes the member line, anchored on the table header: the lines around
    # it are craft-libs `rev`s that upstream bumps, and a recorded anchor quoting one goes stale.
    "Cargo.toml": ["wordcraft-proof-he = { path"],
    "crates/ui-egui/src/i18n.rs": ['code: "he"', "pub static LANGUAGES: [LangInfo;", "fn catalog_texts(self)"],
}


def _same(written: dict, chosen: dict) -> bool:
    """Is `written` (from the table) the change `chosen` (for this layout) applies?"""
    return all(written.get(k, chosen.get(k)) == chosen.get(k) for k in set(written) | set(chosen))


def base_text(root: Path, base: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"], capture_output=True, text=True, check=True).stdout


def hunks_for(before: str, after: str, path: str) -> list[dict]:
    """Every change as a replacement (`old` → `new`) or a pure insertion (`insert` after `after`)."""
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    skips = SKIP_IN.get(path, [])
    hunks: list[dict] = []
    # Where the last change left off, in both files. A hunk may take the lines before it as context
    # to stand out — but not past this line: those lines belong to an earlier change, and a copy of
    # them that both hunks repeat is a block applied twice.
    floor_a = floor_b = 0
    for index, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        old, made = "".join(a[i1:i2]), "".join(b[j1:j2])
        # A pure insertion has no `old` text: its added lines are what the skip looks at.
        if any(marker in old or marker in made for marker in skips):
            floor_a, floor_b = i2, j2
            continue
        previous = [op for op in ops[:index] if op[0] == "equal"]
        before_i, before_j = (previous[-1][2], previous[-1][4]) if previous else (0, 0)
        after_op = next((op for op in ops[index + 1 :] if op[0] != "equal"), None)
        back = min(6, before_i - floor_a, before_j - floor_b)
        forward = min(6, after_op[1] - i2, after_op[3] - j2) if after_op else 6
        if not old.strip():
            for n in range(1, back + 1):
                anchor = "".join(a[before_i - n : before_i])
                if anchor and before.count(anchor) == 1:
                    break
            else:
                raise SystemExit(f"error: {path}: no unique line to insert after:\n{made}")
            hunks.append({"after": anchor, "insert": made})
        else:
            # Context the change shares with the lines around it, so that it stands out: the same
            # lines on both sides, taken from before the change (never from an earlier one) or,
            # when that is not enough, from after it.
            for total in range(0, back + forward + 1):
                for n in range(max(0, total - forward), min(back, total) + 1):
                    m = total - n
                    old_n = "".join(a[before_i - n : before_i]) + old + "".join(a[i2 : i2 + m])
                    new_n = "".join(b[before_j - n : before_j]) + made + "".join(b[j2 : j2 + m])
                    if before.count(old_n) == 1:
                        break
                else:
                    continue
                break
            else:
                raise SystemExit(f"error: {path}: no unique text to replace:\n{old}")
            hunks.append({"old": old_n, "new": new_n})
        floor_a, floor_b = i2, j2
    return hunks


def unfaithful(root: Path, base: str, table: dict[str, list[dict]]) -> list[str]:
    """Replay the table on the base and report the files whose code it does not reproduce.

    A table is only worth replaying if applying it to upstream's tree gives this fork's code: the
    same tokens, whatever the formatting. Anything else (a hunk that repeats lines another hunk
    already wrote, one that no longer matches) would be found by the daily sync, after a push.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from apply_code_overlay import apply_cargo, apply_fonts, apply_hunks, apply_i18n, apply_tests, apply_theme  # noqa: E402

    spelled_out = {
        "Cargo.toml": apply_cargo,
        "crates/ui-egui/src/i18n.rs": apply_i18n,
        "crates/ui-egui/src/i18n/tests.rs": apply_tests,
        "crates/ui-egui/src/theme.rs": apply_theme,
        "crates/ui-egui/src/app/fonts.rs": apply_fonts,
    }
    problems: list[str] = []
    for path, hunks in table.items():
        made, _ = spelled_out.get(path, lambda text: (text, []))(base_text(root, base, path))
        try:
            made, _ = apply_hunks(made, for_layout(hunks, has_legacy_layout(root)), path)
        except SystemExit as gone:
            problems.append(f"{path}: the table does not apply to {base[:12]}: {gone}")
            continue
        if not same_code(made, (root / path).read_text(encoding="utf-8")):
            problems.append(f"{path}: replaying the table on {base[:12]} gives other code than the tree")
    return problems


def missing_from_tree(root: Path, table: dict[str, list[dict]]) -> list[str]:
    """The recorded changes that the tree does not (or does still) show, and stale copies."""
    problems: list[str] = []
    legacy = has_legacy_layout(root)
    for path, hunks in table.items():
        source = (root / path).read_text(encoding="utf-8")
        for hunk in for_layout(hunks, legacy):
            if applied(source, hunk):
                continue
            if "insert" in hunk:
                problems.append(f"{path}: misses the overlay's `{hunk['insert'].strip().splitlines()[0][:60]}`")
            elif not hunk["new"]:
                problems.append(f"{path}: still has the line the overlay removes: `{hunk['old'].strip().splitlines()[0][:60]}`")
            else:
                still = "still has the text the overlay replaces" if has_code(source, hunk["old"]) else "has neither the overlay's text nor the text it replaces"
                problems.append(f"{path}: {still}: `{hunk['old'].strip().splitlines()[0][:60]}`")
    code = root / "i18n-he/code"
    added = sorted(p for p in code.rglob("*") if p.suffix == ".rs" or p.name == "Cargo.toml")
    for copy in added:
        relative = copy.relative_to(code)
        # Voice › Dictate's module is `dictate_patch.py`'s to copy, and its own `--check` says
        # whether it is in place (see `apply_code_overlay.py`'s `voice_patch_file`).
        if relative == Path("crates/ui-egui/src/dictate.rs"):
            continue
        target = root / relative
        if not target.exists():
            problems.append(f"{relative}: missing (copy it from {copy.relative_to(root)})")
        elif not same_code(target.read_text(encoding="utf-8"), copy.read_text(encoding="utf-8")):
            problems.append(f"{relative}: drifted from {copy.relative_to(root)}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="upstream's tree without the overlay (after a sync merge: HEAD^2)")
    parser.add_argument("--check", action="store_true", help="verify the tree still carries every recorded change")
    parser.add_argument("--prune", action="store_true", help="drop the changes the merge made stale, keeping the ones it kept")
    args = parser.parse_args()

    target = root / "i18n-he/code-overlay.json"
    # Voice › Dictate is a patch of its own (`i18n-he/tools/dictate_patch.py`), applied after this
    # table: recording it here would make the overlay add it a second time, and make the daily
    # sync's removal of it leave half of it behind.
    # A file of the other layout (`prefs.rs` before #7101, `lib.rs`'s `UiState` after it) is not in
    # this tree: it has nothing to say about the dictation patch.
    marked = [path for path in FILES if (root / path).exists() and "i18n-he: dictation" in (root / path).read_text(encoding="utf-8")]
    if marked and not args.check:
        raise SystemExit(
            "error: the dictation patch is in the tree ("
            + ", ".join(marked)
            + "): remove it with `python3 i18n-he/tools/dictate_patch.py --remove` before recording, "
            "and put it back afterwards"
        )
    if args.check:
        problems = missing_from_tree(root, json.loads(target.read_text(encoding="utf-8")))
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        if problems:
            return 1
        print("ok: the tree carries every change i18n-he/code-overlay.json records")
        return 0

    if args.prune:
        # After a sync merge, upstream's restructuring leaves recorded changes whose base text is
        # gone: the code they edited moved, or upstream does the thing itself now (#7101 ported the
        # UI onto craft, and `UiState`'s `fonts_lang` went with it). Such a change can never land
        # again, so keeping it would only stop every later run — the sync prunes the table first
        # and commits the merge that carries the prune.
        #
        # The tree here is upstream's *without* the overlay, so "is it applied?" is the wrong
        # question: it is not, for every change. The question is whether it still *applies* — and a
        # change is applied in turn as the table is walked, so a change that follows another in the
        # same file (a deleted line behind an inserted one) is judged on the text the one before it
        # leaves. What no longer applies is what upstream restructured away.
        table = json.loads(target.read_text(encoding="utf-8"))
        legacy = has_legacy_layout(root)
        kept: dict[str, list[dict]] = {}
        dropped = 0
        for path, hunks in table.items():
            file = root / path
            if not file.exists():
                print(f"pruned {path}: upstream removed the file ({len(hunks)} change(s))")
                dropped += len(hunks)
                continue
            source = file.read_text(encoding="utf-8")
            live: list[dict] = []
            for hunk in for_layout(hunks, legacy):
                try:
                    made, _ = apply_hunks(source, [hunk], path)
                except SystemExit:
                    said = (hunk.get("insert") or hunk.get("new") or hunk.get("old") or "").strip().splitlines()
                    print(f"pruned {path}: {said[0][:70] if said else '?'}")
                    dropped += 1
                    continue
                if made == source:
                    # Already there: the tree has this change (a sync run before the overlay).
                    live.append(hunk)
                    continue
                source = made
                live.append(hunk)
            # Keep the entry as it was written (its layout key included), without what went stale.
            if live:
                kept[path] = [h for h in hunks if any(_same(h, k) for k in live)] or live
        kept = {path: hunks for path, hunks in kept.items() if hunks}
        if dropped:
            target.write_text(json.dumps(kept, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"ok: {dropped} stale change(s) pruned, {sum(len(h) for h in kept.values())} kept")
        return 0

    if not args.base:
        parser.error("--base is required to record: it is upstream's tree without the overlay (after a sync merge, HEAD^2)")

    table: dict[str, list[dict]] = {}
    for path in FILES:
        try:
            before = base_text(root, args.base, path)
        except subprocess.CalledProcessError:
            raise SystemExit(f"error: {args.base} has no {path}: wrong base, or upstream moved the file") from None
        # A file upstream has caught up with (it made the same change itself, like the ribbon
        # gallery mirroring in `ribbon/design.rs`) records nothing: keeping an empty entry would
        # only make the table look bigger than the fork's work.
        hunks = hunks_for(before, (root / path).read_text(encoding="utf-8"), path)
        if hunks:
            table[path] = hunks
    # Recording against a tree that already has the overlay would produce an empty table: say so.
    if not any(table.values()):
        raise SystemExit(f"error: {args.base} already contains the overlay: pass upstream's commit, not this fork's")
    target.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"ok: {sum(len(h) for h in table.values())} change(s) in {len(table)} file(s) recorded")
    problems = missing_from_tree(root, table) + unfaithful(root, args.base, table)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
