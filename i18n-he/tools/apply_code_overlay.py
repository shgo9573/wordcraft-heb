#!/usr/bin/env python3
"""Apply this fork's Hebrew code changes to a checkout of upstream, idempotently.

The Hebrew catalog itself is data (`i18n-he/locales/he/`), but offering it needs four small code
changes: the `he` row in `LANGUAGES`, a public `Lang::catalog_texts`, the interface font fallback
for scripts Inter lacks (`theme::interface_char_covered`, `theme::faces_for_interface_text`) and
its call in `install_ui_fonts`. They are committed in this fork; upstream's daily merge rewrites
the same files, so after a conflict the workflow takes upstream's version and re-applies them with
this script. Running it on a tree that already has them changes nothing.

    python3 i18n-he/tools/apply_code_overlay.py            # apply
    python3 i18n-he/tools/apply_code_overlay.py --check    # only report what is missing

The right-to-left interface and Hebrew proofing are larger: `code-overlay.json` lists, per upstream
file, the exact upstream text a change replaces (or the line it goes after) and the text it becomes,
and `code/` holds the files this fork adds whole (`crates/ui-egui/src/rtl.rs`,
`crates/proof/src/he/`). `--check` also reports when a copy in `code/` has drifted from the file it
mirrors.

Exit 1 when a change could not be applied: upstream has moved the code the change hangs on, and a
person has to look.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from code_match import CODE_TOKEN, code_matches, has_code  # noqa: E402  (the sibling matcher)

HE_ROW = '''    // Hebrew, right to left; `he`, `he-IL` and `he_IL.UTF-8` resolve here. Its catalog is
    // this fork's (`i18n-he/`, laid over craft-i18n by `i18n-he/tools/assemble.py`), not
    // storytold/craft-i18n's: it is embedded whenever that overlay is in `CRAFT_I18N_DIR`. The
    // interface mirrors right to left ([`Lang::is_rtl`], `crate::rtl`), and WordCraft proofs
    // Hebrew (`ProofLang::He`), so new documents are written in Hebrew.
    LangInfo { code: "he", prefer_hans: false, editing_lang: Some("he-IL") },
'''

TESTS_HELPER = """/// Does this build embed this fork's Hebrew catalog? A catalog directory laid out from
/// storytold/craft-i18n alone (`craft-i18n.rev`) has no `he` yet, so Hebrew is listed but not
/// offered there; the daily build lays `i18n-he/` over it (`i18n-he/tools/assemble.py`).
fn offers_hebrew() -> bool {
    CRAFT_I18N.iter().any(|(code, ..)| *code == "he")
}

"""

TESTS_HELPER_ANCHOR = "/// The translations in `code`'s embedded WordCraft catalog, plural forms apart: the fonts must"

TESTS_AVAILABLE = '    assert!(r["available"].as_array().is_some_and(|a| a.len() == LANGUAGES.len()));'

TESTS_AVAILABLE_PATCHED = '    assert!(r["available"].as_array().is_some_and(|a| a.len() == LANGUAGES.len() - usize::from(!offers_hebrew())));'

TESTS_LISTED = """    let listed: Vec<&str> = LANGUAGES.iter().map(|l| l.code).collect();
    assert_eq!(all, listed, "every language WordCraft lists has its catalog in craft-i18n");"""

TESTS_LISTED_PATCHED = """    // This fork's Hebrew is offered only when its overlay is embedded (see `offers_hebrew`).
    let listed: Vec<&str> = LANGUAGES.iter().map(|l| l.code).filter(|c| *c != "he" || offers_hebrew()).collect();
    assert_eq!(all, listed, "every language WordCraft lists has its catalog in craft-i18n");"""

THEME_FUNCTIONS = '''/// A character the interface fonts draw without borrowing a document face: ASCII and Latin-1
/// ([`caption_char_covered`]), the Greek, Cyrillic and Armenian ranges of Inter and Source Sans,
/// the punctuation and symbol blocks egui's own icon and emoji faces cover, and CJK (the CJK UI
/// font). Hebrew, Arabic, Thai … are not covered: the interface needs a document face for them.
pub fn interface_char_covered(c: char) -> bool {
    caption_char_covered(c) || matches!(c, '\\u{0370}'..='\\u{052F}' | '\\u{2000}'..='\\u{2BFF}')
}

/// The document faces the interface text itself needs: characters of `texts` (a language's
/// catalogs and its own name, in the interface fonts' own size) that no embedded interface face
/// draws. Hebrew, Arabic and Thai menus would otherwise be rows of boxes; each script's letters
/// come from a document fallback face, exactly as the caption and the comments take theirs
/// (#565, #2067). Looked at once per interface install, not per frame.
pub fn faces_for_interface_text(texts: impl Iterator<Item = &'static str>) -> Vec<Arc<wordcraft_fonts::FontFace>> {
    let mut out: Vec<Arc<wordcraft_fonts::FontFace>> = Vec::new();
    for text in texts {
        for face in faces_for_preedit(text, &out, interface_char_covered, |c| wordcraft_fonts::FontDb::global().fallback_for(c, u32::MAX)) {
            out.push(face);
        }
    }
    out
}

'''

THEME_ANCHOR = "/// Document faces needed to draw `text` (the input method's composition, or a file name in the"

DOC_BLOCK = """//! # Hebrew (this fork)
//! Hebrew is not in storytold/craft-i18n yet, so its catalogs live in this fork, in
//! `i18n-he/locales/he/` (`README.md` there): `i18n-he/tools/assemble.py` lays them over a
//! craft-i18n checkout to make the `CRAFT_I18N_DIR` a build embeds, and the daily
//! `sync-upstream` workflow does that against upstream's newest `main`. Strings with no Hebrew
//! row show in English, so the catalog can grow without breaking anything.
//!
"""

DOC_ANCHOR = "//! # Adding a language\n"

FONTS_ANCHOR = "            let mut faces = self.canvas.ime_faces.clone();\n"

FONTS_LINES = '''            // Interface text in a script the interface faces leave out (Hebrew, Arabic, Thai …)
            // borrows a document face, as the caption does: the Hebrew menus, dialogs and the
            // language picker would otherwise draw as boxes. Looked at again only when the fonts
            // are installed, that is when the language changes.
            //
            // Every language's own name, not just this one's: File ▸ Options lists them all, so a
            // Hebrew interface (the default) shows „עברית” in that list before Hebrew is the
            // current language — and after switching away from it.
            let names = i18n::Lang::all().map(i18n::Lang::name);
            faces.extend(theme::faces_for_interface_text(lang.catalog_texts().chain(names)));
'''


def missing_he_row(source: str) -> bool:
    return 'code: "he"' not in source


HE_ROW_ANY = re.compile(r'    // Hebrew, right to left;.*?\n(?:    //.*?\n)*    LangInfo \{ code: "he", prefer_hans: false, editing_lang: [^}]*\},\n', re.S)


def apply_i18n(source: str) -> tuple[str, list[str]]:
    """The `he` row in `LANGUAGES` and the public `catalog_texts`."""
    notes: list[str] = []
    if not missing_he_row(source) and HE_ROW not in source:
        # A row the earlier overlay wrote (it said the interface stays left to right): bring it up
        # to date, since the row now carries the Hebrew editing language.
        source, count = HE_ROW_ANY.subn(HE_ROW, source, count=1)
        if count:
            notes.append("i18n.rs: the `he` row (Hebrew editing language)")
    if missing_he_row(source):
        declaration = re.search(r"pub static LANGUAGES: \[LangInfo; (\d+)\] = \[", source)
        if not declaration:
            raise SystemExit("error: i18n.rs has no `pub static LANGUAGES: [LangInfo; N] = [`")
        end = source.find("\n];", declaration.end())
        if end < 0:
            raise SystemExit("error: i18n.rs's LANGUAGES array has no closing `];`")
        count = int(declaration.group(1))
        source = source[: end + 1] + HE_ROW + source[end + 1 :]
        source = source[: declaration.start()] + f"pub static LANGUAGES: [LangInfo; {count + 1}] = [" + source[declaration.end() :]
        notes.append(f"LANGUAGES: added `he` ({count} → {count + 1})")
    if "//! # Hebrew (this fork)" not in source:
        if DOC_ANCHOR not in source:
            raise SystemExit("error: i18n.rs has no `//! # Adding a language` section")
        source = source.replace(DOC_ANCHOR, DOC_BLOCK + DOC_ANCHOR, 1)
        notes.append("i18n.rs: the Hebrew section of the module docs")
    if "    fn catalog_texts(self)" in source:
        source = source.replace("    fn catalog_texts(self)", "    pub fn catalog_texts(self)", 1)
        notes.append("i18n.rs: `Lang::catalog_texts` is public")
    return source, notes


def apply_theme(source: str) -> tuple[str, list[str]]:
    if "fn faces_for_interface_text" in source:
        return source, []
    if THEME_ANCHOR not in source:
        raise SystemExit(f"error: theme.rs has no anchor for the interface fallback ({THEME_ANCHOR!r})")
    return source.replace(THEME_ANCHOR, THEME_FUNCTIONS + THEME_ANCHOR, 1), ["theme.rs: interface text fallback faces"]


def apply_tests(source: str) -> tuple[str, list[str]]:
    """The two i18n tests that count the offered languages: Hebrew exists only with the overlay."""
    if "fn offers_hebrew()" in source:
        return source, []
    notes: list[str] = []
    if TESTS_HELPER_ANCHOR not in source:
        raise SystemExit("error: i18n/tests.rs has no anchor for `offers_hebrew`")
    source = source.replace(TESTS_HELPER_ANCHOR, TESTS_HELPER + TESTS_HELPER_ANCHOR, 1)
    if TESTS_AVAILABLE not in source:
        raise SystemExit("error: i18n/tests.rs has no `available` length assertion")
    source = source.replace(TESTS_AVAILABLE, TESTS_AVAILABLE_PATCHED, 1)
    if TESTS_LISTED not in source:
        raise SystemExit("error: i18n/tests.rs has no `the_languages_offered_are_the_embedded_ones_of_the_list` body")
    source = source.replace(TESTS_LISTED, TESTS_LISTED_PATCHED, 1)
    notes.append("i18n/tests.rs: the offered languages count with the overlay")
    return source, notes


def apply_fonts(source: str) -> tuple[str, list[str]]:
    if "faces_for_interface_text" in source:
        return source, []
    if FONTS_ANCHOR not in source:
        raise SystemExit("error: app/fonts.rs has no `let mut faces = self.canvas.ime_faces.clone();`")
    return source.replace(FONTS_ANCHOR, FONTS_ANCHOR + FONTS_LINES, 1), ["app/fonts.rs: borrow document faces for the interface text"]


def _candidates(source: str, text: str, anchor: bool) -> list[tuple[int, int]]:
    """Every place `source` could have `text`: exact first, then as code (whitespace ignored)."""
    exact = [match.span() for match in re.finditer(re.escape(text), source)]
    if exact:
        return exact
    where = code_matches(source, text)
    spans = [match.span() for match in where]
    return [span for span in spans if _whole_lines(source, span)] if anchor else spans


def locate(source: str, text: str, name: str, what: str, anchor: bool) -> tuple[int, int] | None:
    """Where `source` has `text`, or None; SystemExit when it has it more than once.

    The text is looked for exactly first, which keeps the precision a hunk was recorded with (the
    indentation of an anchor tells one closing brace from another). Only when the exact text has
    moved — `cargo fmt` re-wrapped it on this fork's `main` — is it looked for as code, whitespace
    ignored; an anchor then has to be a whole line or lines, since without its indentation a short
    one (`}`, a blank line) would match in many places.
    """
    where = _candidates(source, text, anchor)
    if len(where) > 1:
        raise SystemExit(f"error: {name} has the text a Hebrew change {what} {len(where)} times:\n{text.strip().splitlines()[0][:70]}")
    return where[0] if where else None


def _whole_lines(source: str, span: tuple[int, int]) -> bool:
    """Does `span` start a line and end one?"""
    start, end = span
    starts_line = start == 0 or source[start - 1] == "\n"
    ends_line = end == len(source) or source[end] == "\n"
    return starts_line and ends_line


def _tokens(text: str) -> list[str]:
    return CODE_TOKEN.findall(text)


def _contains_code(haystack: str, needle: str) -> bool:
    """Is the code in `needle` in `haystack`, as one unbroken run of tokens, one inside another?"""
    outer, inner = _tokens(haystack), _tokens(needle)
    if not inner:
        return True
    return any(outer[k : k + len(inner)] == inner for k in range(len(outer) - len(inner) + 1))


def _applied(source: str, hunk: dict, name: str) -> bool:
    """Is this hunk already in `source`?

    A replacement is applied when its new code is there and its old code is not (or when the new
    code keeps the old one, as a change that only adds lines does). An insertion is applied when it
    is where it goes — right after its anchor — because a short one (a lone `}`) is everywhere.
    """
    if "insert" in hunk:
        inserted = _tokens(hunk["insert"])
        where = _candidates(source, hunk["after"], anchor=True)
        if not where:
            # The line it goes after is gone (a later hunk, or upstream): the hunk is applied when
            # what it inserts is somewhere in the file.
            return has_code(source, hunk["insert"])
        return any(_tokens(source[end:])[: len(inserted)] == inserted for _, end in where)
    old, new = hunk["old"], hunk["new"]
    if not has_code(source, new):
        return False
    return not has_code(source, old) or _contains_code(new, old)


def apply_hunks(source: str, hunks: list[dict], name: str) -> tuple[str, list[str]]:
    """The edits `code-overlay.json` lists for a file, idempotently.

    A hunk replaces `old` with `new`, or inserts `insert` after the line `after`. A hunk already
    applied is skipped ([`_applied`]), so running this on this fork's own tree changes nothing —
    however that tree is formatted ([`locate`]).
    """
    notes: list[str] = []
    for hunk in hunks:
        if _applied(source, hunk, name):
            continue
        if "old" in hunk and not hunk["new"]:
            found = locate(source, hunk["old"], name, "removes", anchor=False)
            if found is None:
                continue
            source = _drop_line(source, *found)
            notes.append(f"{name}: removed {hunk['old'].strip().splitlines()[0][:60]}")
            continue
        if "old" in hunk:
            found = locate(source, hunk["old"], name, "replaces", anchor=False)
            if found is None:
                raise SystemExit(f"error: {name} no longer has the text a Hebrew change replaces:\n{hunk['old']}")
            start, end = found
            source = source[:start] + _keep_break(source, end, hunk["new"]) + source[end:]
        else:
            found = locate(source, hunk["after"], name, "follows", anchor=True)
            if found is None:
                raise SystemExit(f"error: {name} no longer has the line a Hebrew change follows:\n{hunk['after']}")
            _, end = found
            # Right after the anchor line; a code match stops at its last character, before the
            # line break the anchor's text had.
            at = end
            if source[end - 1 : end] != "\n":
                line_end = source.find("\n", end)
                at = end if line_end == -1 else line_end + 1
            source = source[:at] + hunk["insert"] + source[at:]
        first = next((line.strip() for line in hunk.get("insert", hunk.get("new", "")).splitlines() if line.strip()), "")
        notes.append(f"{name}: {first[:70]}")
    return source, notes


def _keep_break(source: str, end: int, new: str) -> str:
    """`new`, without adding a line break the source already has where the old text ended."""
    if new.endswith("\n") and source[end : end + 1] == "\n":
        return new[:-1]
    return new


def _drop_line(source: str, start: int, end: int) -> str:
    """`source` without the span, and without the blank line it would leave behind."""
    if source[end : end + 1] == "\n":
        end += 1
    if source[start - 1 : start] == "\n" and source[end : end + 1] == "\n":
        end += 1
    return source[:start] + source[end:]


def apply_generic(root: Path, path: Path, hunks: list[dict]) -> tuple[str, list[str]]:
    name = str(path.relative_to(root))
    return apply_hunks(path.read_text(encoding="utf-8"), hunks, name)


def copy_new_files(root: Path, code: Path, check: bool, missing: list[str]) -> list[str]:
    """The files this fork adds whole: `code/crates/...` mirrors the tree's `crates/...`."""
    notes: list[str] = []
    for source in sorted(code.rglob("*.rs")):
        relative = source.relative_to(code)
        target = root / relative
        if check:
            if not target.exists():
                missing.append(f"{relative}: missing (copy it from {source.relative_to(root)})")
            elif target.read_bytes() != source.read_bytes():
                missing.append(f"{relative}: drifted from {source.relative_to(root)}")
            continue
        if target.exists() and target.read_bytes() == source.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        notes.append(f"{relative}: copied")
    return notes


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report what is missing instead of writing")
    parser.add_argument("--files", action="store_true", help="print the files the overlay writes, one per line")
    args = parser.parse_args()

    # The four changes the Hebrew catalog alone needs, spelled out above.
    targets = {
        root / "crates/ui-egui/src/i18n.rs": (apply_i18n, ["pub fn catalog_texts", 'code: "he"']),
        root / "crates/ui-egui/src/theme.rs": (apply_theme, ["fn faces_for_interface_text", "fn interface_char_covered"]),
        root / "crates/ui-egui/src/app/fonts.rs": (apply_fonts, ["faces_for_interface_text"]),
        root / "crates/ui-egui/src/i18n/tests.rs": (apply_tests, ["fn offers_hebrew()"]),
    }
    # Everything the right-to-left interface and Hebrew proofing touch, checked against upstream's
    # exact text (`code-overlay.json`) plus the files this fork adds whole (`code/`).
    hunks: dict[str, list[dict]] = json.loads((root / "i18n-he/code-overlay.json").read_text(encoding="utf-8"))
    generics = {root / relative: patch for relative, patch in hunks.items()}
    code = root / "i18n-he/code"

    if args.files:
        # The workflow takes upstream's version of a conflicting one of these and runs the overlay
        # again, so the list has to come from the overlay itself, not a copy of it.
        paths = {path.relative_to(root) for path in list(targets) + list(generics)}
        paths |= {path.relative_to(code) for path in code.rglob("*.rs")}
        for path in sorted(paths):
            print(path)
        return 0

    missing: list[str] = []
    if args.check:
        for path, (_, markers) in targets.items():
            source = path.read_text(encoding="utf-8")
            missing += [f"{path.relative_to(root)}: no `{m}`" for m in markers if m not in source]
        for path, patch in generics.items():
            source = path.read_text(encoding="utf-8") if path.exists() else ""
            for hunk in patch:
                applied, wanted = hunk.get("insert", hunk.get("new", "")), hunk.get("old", hunk.get("after", ""))
                # A deleting hunk leaves nothing to look for: it is applied when its text is gone.
                if (not has_code(source, applied)) if applied else has_code(source, wanted):
                    missing.append(f"{path.relative_to(root)}: no `{wanted.strip().splitlines()[0][:70]}`")
        missing += copy_new_files(root, code, check=True, missing=[])
        for line in missing:
            print(f"error: {line}", file=sys.stderr)
        if missing:
            return 1
        print("ok: the Hebrew code overlay is in place")
        return 0

    changed = 0
    for path, (apply, _) in targets.items():
        source = path.read_text(encoding="utf-8")
        patched, notes = apply(source)
        if patched != source:
            path.write_text(patched, encoding="utf-8", newline="\n")
            changed += 1
        for note in notes:
            print(note)
    for path, patch in generics.items():
        source = path.read_text(encoding="utf-8")
        patched, notes = apply_generic(root, path, patch)
        if patched != source:
            path.write_text(patched, encoding="utf-8", newline="\n")
            changed += 1
        for note in notes:
            print(note)
    for note in copy_new_files(root, code, check=False, missing=[]):
        print(note)
        changed += 1
    print("ok: nothing to do, the overlay is already in place" if changed == 0 else f"ok: {changed} file(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
