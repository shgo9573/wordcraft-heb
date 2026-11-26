#!/usr/bin/env python3
"""Apply — or take back — this fork's **dictation** patch: Voice › Dictate on a local speech service.

    python3 i18n-he/tools/dictate_patch.py --apply     # after the overlay, before a build
    python3 i18n-he/tools/dictate_patch.py --remove    # the build without it
    python3 i18n-he/tools/dictate_patch.py --check     # is it in place, and does the tree agree?

Dictation is not part of the Hebrew overlay proper (`code-overlay.json`): it is a small, separate
feature — `crates/ui-egui/src/dictate.rs` plus seven one-or-two-line edits around it — and the
daily sync is allowed to build **without** it. A workflow that finds the patch no longer fits
upstream's code (an anchor gone, the module moved, `cargo check` failing on it) runs `--remove`
and builds the plain Hebrew app, so a change upstream can never keep a release from coming out.

Every line the patch adds carries the marker `i18n-he: dictation`, and `--remove` deletes exactly
the marked lines (the whole module goes too). That is what makes the removal safe to run on a tree
the patch was applied to by any means: it never guesses.

The anchors below are upstream's text, so a changed upstream is reported (`--check`) rather than
silently patched in the wrong place.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "i18n-he: dictation"

# The module the patch adds whole, from `i18n-he/code/` (the same place the Hebrew overlay's own
# added crate lives).
MODULE = "crates/ui-egui/src/dictate.rs"

# Each edit: the file, the line of upstream's the patch goes after (or before), and the marked
# lines it adds. A file may appear more than once.
EDITS: list[dict] = [
    {
        "file": "crates/ui-egui/src/lib.rs",
        # One line, between `dialogs` and `documents` where the alphabetised module list keeps it,
        # and with its comment on the same line: `cargo fmt` re-sorts a module list and would carry
        # a comment of its own to the old place, leaving the patch half-applied on the next run.
        "after": "pub mod dialogs;\n",
        "lines": [
            f"pub mod dictate; // {MARKER} — Voice › Dictate on a local speech service (see `i18n-he/`).\n",
        ],
    },
    {
        "file": "crates/ui-egui/src/lib.rs",
        "after": "    pub(crate) updates_rt: updates_ui::Runtime,\n",
        "lines": [
            f"    /// {MARKER} — the run, and the sentences it hears.\n",
            "    pub(crate) dictation: crate::dictate::Dictation,\n",
        ],
    },
    {
        # `swap_window` destructures `WordApp` exhaustively, so a new app-wide field must be named
        # there too (app-wide state stays with the app, not with a window).
        "file": "crates/ui-egui/src/window_ui.rs",
        "optional": True,
        "after": "            updates_rt: _,\n",
        "lines": [f"            dictation: _, // {MARKER}: app-wide, like `updates_rt`\n"],
    },
    {
        "file": "crates/ui-egui/src/app.rs",
        "after": "            updates_rt: updates_ui::Runtime::default(),\n",
        "lines": [f"            dictation: Default::default(), // {MARKER}\n"],
    },
    {
        "file": "crates/ui-egui/src/app/frame.rs",
        "after": "        crate::font_download::tick(self);\n",
        "lines": [f"        crate::dictate::tick(self); // {MARKER}\n"],
    },
    {
        "file": "crates/ui-egui/src/app/commands.rs",
        # The doc comment over `works_without_document`: while the ribbon's Voice group is drawn
        # there is always a document, so the command only has to be callable to stop being grey.
        "after": 'pub(crate) fn works_without_document(id: &str) -> bool {\n',
        "lines": [
            f"    // {MARKER}: Dictate is offered in every window, and its own `enabled` decides.\n",
            '    if id == "tools.dictate" {\n',
            "        return true;\n",
            "    }\n",
        ],
    },
    {
        "file": "crates/ui-egui/src/app/commands.rs",
        # `render`'s last `ui.*` arm: an id nothing else answers reaches `None`, so this goes last.
        "after": '                json!({"displayServer": self.ui.display_server.code()})\n            }\n',
        "lines": [
            f"            // {MARKER} — records through a local speech service and types what it hears at\n",
            "            // the caret; a second call stops it, and `ui.dictateCancel` cancels too.\n",
            '            "tools.dictate" => match self.dictate() {\n',
            "                Ok(v) => v,\n",
            "                Err(e) => return Some(Err(e)),\n",
            "            },\n",
            '            "ui.dictateCancel" if self.dictation.running() => {\n',
            "                self.stop_dictating();\n",
            '                json!({"listening": false})\n',
            "            }\n",
        ],
    },
    # Where the ribbon asks whether a command is enabled. Upstream has moved this twice (before
    # #7310 it was `widgets/buttons.rs`'s `enabled`, after it `app/command_board.rs`'s `gate`), and
    # both spellings are patched: a file upstream no longer has is simply not written. The same rule
    # in both: Dictate exists, and a local speech service does the recording, in the desktop app.
    {
        "file": "crates/ui-egui/src/widgets/buttons.rs",
        "optional": True,
        "after": '        None if id == "ui.crop" => crate::crop::can_toggle(app),\n',
        "lines": [
            f"        // {MARKER} — a local speech service does the recording, in the desktop app.\n",
            '        None if id == "tools.dictate" => !cfg!(target_arch = "wasm32"),\n',
        ],
    },
    {
        "file": "crates/ui-egui/src/app/command_board.rs",
        "optional": True,
        "after": '        None if id == "ui.crop" => (crate::crop::can_toggle(app), None),\n',
        "lines": [
            f"        // {MARKER} — a local speech service does the recording, in the desktop app.\n",
            '        None if id == "tools.dictate" => (!cfg!(target_arch = "wasm32"), None),\n',
        ],
    },
    # Upstream publishes a disabled state for every catalog id no command implements (#7310), and
    # its own test names Dictate as one of them. With a command behind it the id is no longer
    # unimplemented: it joins the gated interface commands (so its state is the real one above), and
    # the test stops listing it.
    {
        "file": "crates/ui-egui/src/app/command_board.rs",
        "optional": True,
        "after": '    ("ui.zotero.removeCodes", "Unlink Citations"),\n',
        "lines": [f'    ("tools.dictate", "Dictate"), // {MARKER}\n'],
    },
    {
        "file": "crates/ui-egui/src/app/command_board.rs",
        "optional": True,
        "replace": [('for id in ["tools.dictate", "draw.inkToMath", "review.translate", "review.blockAuthors"] {', 'for id in ["draw.inkToMath", "review.translate", "review.blockAuthors"] {')],
    },
    {
        "file": "crates/ui-egui/src/ribbon/home.rs",
        "optional": True,
        "after": '    group(ui, "Voice", None, app, |ui, app| {\n',
        "replace": [
            (
                '        big(ui, app, "dictate", "Dictate", "tools.dictate", json!({}), false);\n',
                f"        // {MARKER} — it stays pressed while it records.\n"
                '        big_toggle(ui, app, "dictate", "Dictate", "tools.dictate", app.dictation.listening);\n',
            )
        ],
    },
    # The icon the toggle needs. Upstream's newer ribbon has no one-line import list (`big_toggle`
    # comes with the widgets); this fork's older one lists it, and the list is extended.
    {
        "file": "crates/ui-egui/src/ribbon/home.rs",
        "optional": True,
        "replace": [
            (
                "use super::{Remember, Stroke, Target, Tokens, Ui, Value, WordApp, big, group, json, menu_button, small, split, vec2};\n",
                f"// {MARKER}\n"
                "use super::{Remember, Stroke, Target, Tokens, Ui, Value, WordApp, big, big_toggle, group, json, menu_button, small, split, vec2};\n",
            )
        ],
    },
]

# The old upstream text the removal puts back: the `big_toggle` call and the import it needs, and
# the commands.rs arm the marked comment introduced.
COMMAND_COMMENT = (
    f"            // {MARKER} — records through a local speech service and types what it hears at\n"
    "            // the caret; a second call stops it, and `ui.dictateCancel` cancels too.\n"
)
COMMAND_ARM = (
    '            "tools.dictate" => match self.dictate() {\n'
    "                Ok(v) => v,\n"
    "                Err(e) => return Some(Err(e)),\n"
    "            },\n"
    '            "ui.dictateCancel" if self.dictation.running() => {\n'
    "                self.stop_dictating();\n"
    '                json!({"listening": false})\n'
    "            }\n"
)


def applied(source: str, edit: dict) -> bool:
    """Whether `edit` is already in `source`."""
    if "any_of" in edit:
        return any(applied(source, choice) for choice in edit["any_of"])
    if "replace" in edit:
        return all(new in source for _, new in edit["replace"])
    inserted = "".join(edit["lines"])
    # `rustfmt` re-sorts the module list and the imports, and it may move a line an edit added to
    # another `pub mod` (`dictate` sits between `desktop_theme` and `dialogs`, not after `crop`):
    # the block being there is what matters, not where it sits. An edit that *replaces* text is
    # checked by its text below.
    if inserted in source:
        return True
    if "after" in edit:
        anchor = edit["after"]
        at = source.find(anchor)
        return at >= 0 and source.startswith(inserted, at + len(anchor))
    if "before" in edit:
        anchor = edit["before"]
        at = source.find(anchor)
        return at >= 0 and source[:at].endswith("".join(edit["lines"]))
    raise SystemExit("error: an edit has neither `after`, `before` nor `replace`")


def anchor_present(source: str, edit: dict) -> bool:
    if "any_of" in edit:
        return any(anchor_present(source, choice) for choice in edit["any_of"])
    if "replace" in edit:
        return any(old in source for old, _ in edit["replace"]) or applied(source, edit)
    if "after" in edit:
        return edit["after"] in source or applied(source, edit)
    return edit["before"] in source or applied(source, edit)


def apply(root: Path) -> int:
    source_of = {}
    for edit in EDITS:
        path = root / edit["file"]
        # A layout upstream has dropped: nothing to patch, and nothing to report.
        if edit.get("optional") and edit["file"] not in source_of and not path.is_file():
            continue
        source = source_of.get(edit["file"], path.read_text(encoding="utf-8"))
        if applied(source, edit):
            source_of[edit["file"]] = source
            continue
        if "any_of" in edit:
            for choice in edit["any_of"]:
                if any(old in source for old, _ in choice["replace"]):
                    for old, new in choice["replace"]:
                        source = source.replace(old, new, 1)
                    break
            else:
                print(f"error: {edit['file']}: the text this patch replaces is gone", file=sys.stderr)
                return 1
        elif "replace" in edit:
            missing = [old for old, _ in edit["replace"] if old not in source]
            if missing and edit.get("optional"):
                source_of[edit["file"]] = source
                continue  # not this layout: skip it rather than leave the file half patched
            if missing:
                print(f"error: {edit['file']}: the text this patch replaces is gone:\n{missing[0]}", file=sys.stderr)
                return 1
            for old, new in edit["replace"]:
                source = source.replace(old, new, 1)
        elif "after" in edit:
            anchor = edit["after"]
            at = source.find(anchor)
            if at < 0:
                print(f"error: {edit['file']}: no line to insert after: {anchor.strip()[:70]}", file=sys.stderr)
                return 1
            source = source[: at + len(anchor)] + "".join(edit["lines"]) + source[at + len(anchor) :]
        else:
            anchor = edit["before"]
            at = source.find(anchor)
            if at < 0:
                print(f"error: {edit['file']}: no line to insert before: {anchor.strip()[:70]}", file=sys.stderr)
                return 1
            source = source[:at] + "".join(edit["lines"]) + source[at:]
        source_of[edit["file"]] = source
    for file, source in source_of.items():
        (root / file).write_text(source, encoding="utf-8", newline="\n")
    # The module, from the copy this fork keeps with the other whole files.
    module = root / "i18n-he/code" / MODULE
    if not module.is_file():
        print(f"error: {module.relative_to(root)} is missing: the patch has nothing to copy", file=sys.stderr)
        return 1
    target = root / MODULE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(module.read_bytes())
    print(f"ok: dictation is in place ({MODULE}, {len(EDITS)} edit(s) in {len(source_of)} file(s))")
    return 0


def remove(root: Path) -> int:
    """Delete every marked line, put back what a marked line replaced, and drop the module."""
    changed = 0
    files = sorted({edit["file"] for edit in EDITS})
    for file in files:
        path = root / file
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        before = source
        for edit in EDITS:
            if edit["file"] != file:
                continue
            # An insertion goes by its exact text, wherever it ended up; `rustfmt` may have carried
            # the comment that introduced it somewhere else in the file, so the comment goes too.
            if "replace" not in edit and "any_of" not in edit:
                block = "".join(edit["lines"])
                if block in source:
                    source = source.replace(block, "", 1)
                    continue
                # `rustfmt` may have moved a line an insertion added to another place in the file
                # (the module list is alphabetised, `pub mod dictate` went between `dialogs` and
                # `documents`). Only lines that are unique in the file go that way: a generic line
                # of an inserted block (a closing brace) would otherwise take someone else's.
                for line in edit["lines"]:
                    if source.count(line) == 1:
                        source = source.replace(line, "", 1)
                continue
        source = source.replace(COMMAND_ARM, "").replace(COMMAND_COMMENT, "")
        for edit in EDITS:
            if edit["file"] != file:
                continue
            # A replacement is put back by name; an insertion is taken out whole.
            for old, new in edit.get("replace", []) + [pair for choice in edit.get("any_of", []) for pair in choice["replace"]]:
                source = source.replace(new, old)
            if "replace" in edit or "any_of" in edit:
                continue
            inserted = "".join(edit["lines"])
            if "after" in edit:
                anchor = edit["after"]
                source = source.replace(anchor + inserted, anchor)
            else:
                anchor = edit["before"]
                source = source.replace(inserted + anchor, anchor)
        # Whatever a part-applied patch left behind: every marked line and its comment run.
        source = re.sub(rf"^\s*//.*{re.escape(MARKER)}.*\n", "", source, flags=re.M)
        if source != before:
            path.write_text(source, encoding="utf-8", newline="\n")
            changed += 1
    module = root / MODULE
    if module.is_file():
        module.unlink()
        changed += 1
    print(f"ok: dictation is out ({changed} file(s) changed)" if changed else "ok: dictation was not in the tree")
    return 0


def check(root: Path) -> int:
    problems: list[str] = []
    # The command's own gate: one of the two layouts must carry it (see `EDITS`).
    gate = [edit for edit in EDITS if edit.get("optional") and "None if id ==" in "".join(edit.get("lines", []))]
    if not any(applied((root / edit["file"]).read_text(encoding="utf-8"), edit) for edit in gate if (root / edit["file"]).is_file()):
        problems.append("no `None if id == \"tools.dictate\"` arm: Dictate would be greyed out wherever it is not registered")
    for edit in EDITS:
        path = root / edit["file"]
        # An optional edit belongs to one of two layouts: when this tree has neither its anchor nor
        # its text, the layout it patches is not here, which is not a problem.
        if edit.get("optional") and not path.is_file():
            continue
        if edit.get("optional") and not applied(path.read_text(encoding="utf-8"), edit) and not anchor_present(path.read_text(encoding="utf-8"), edit):
            continue
        source = path.read_text(encoding="utf-8")
        if not applied(source, edit):
            problems.append(f"{edit['file']}: the patch's edit is not in place")
    if not (root / MODULE).is_file():
        problems.append(f"{MODULE}: missing (copy it from i18n-he/code/{MODULE})")
    elif (root / MODULE).read_bytes() != (root / "i18n-he/code" / MODULE).read_bytes():
        problems.append(f"{MODULE}: drifted from i18n-he/code/")
    # Anchors still where the patch expects them, so a later `--apply` lands right.
    for edit in EDITS:
        path = root / edit["file"]
        if edit.get("optional") and not path.is_file():
            continue
        source = path.read_text(encoding="utf-8") if path.is_file() else ""
        if edit.get("optional") and not applied(source, edit):
            continue
        if not anchor_present(source, edit):
            what = edit.get("replace", [("", "")])[0][0] if "replace" in edit else (edit.get("after") or edit["before"])
            problems.append(f"{edit['file']}: the line the patch anchors on is gone: {what.strip()[:60]}")
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    if problems:
        return 1
    print("ok: the dictation patch is in place, and its anchors still match this tree")
    return 0


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="the tree to patch (default: this checkout); for trying a newer upstream")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="put the dictation patch in place")
    group.add_argument("--remove", action="store_true", help="take it back out (the build without it)")
    group.add_argument("--check", action="store_true", help="report a patch that is not in place, or anchors that moved")
    args = parser.parse_args()
    if args.root:
        root = Path(args.root).resolve()
    if args.apply:
        return apply(root)
    if args.remove:
        return remove(root)
    return check(root)


if __name__ == "__main__":
    sys.exit(main())
