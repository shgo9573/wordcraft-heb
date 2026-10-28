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

Exit 1 when a change could not be applied: upstream has moved the code the change hangs on, and a
person has to look.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HE_ROW = '''    // Hebrew, right to left; `he`, `he-IL` and `he_IL.UTF-8` resolve here. Its catalog is
    // this fork's (`i18n-he/`, laid over craft-i18n by `i18n-he/tools/assemble.py`), not
    // storytold/craft-i18n's: it is embedded whenever that overlay is in `CRAFT_I18N_DIR`. The
    // interface keeps its left-to-right layout, and each Hebrew label lays out right to left.
    LangInfo { code: "he", prefer_hans: false, editing_lang: None },
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
            faces.extend(theme::faces_for_interface_text(lang.catalog_texts().chain(std::iter::once(lang.name()))));
'''


def missing_he_row(source: str) -> bool:
    return 'code: "he"' not in source


def apply_i18n(source: str) -> tuple[str, list[str]]:
    """The `he` row in `LANGUAGES` and the public `catalog_texts`."""
    notes: list[str] = []
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


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report what is missing instead of writing")
    args = parser.parse_args()

    targets = {
        root / "crates/ui-egui/src/i18n.rs": (apply_i18n, ["pub fn catalog_texts", 'code: "he"']),
        root / "crates/ui-egui/src/theme.rs": (apply_theme, ["fn faces_for_interface_text", "fn interface_char_covered"]),
        root / "crates/ui-egui/src/app/fonts.rs": (apply_fonts, ["faces_for_interface_text"]),
        root / "crates/ui-egui/src/i18n/tests.rs": (apply_tests, ["fn offers_hebrew()"]),
    }
    if args.check:
        missing = []
        for path, (_, markers) in targets.items():
            source = path.read_text(encoding="utf-8")
            missing += [f"{path.relative_to(root)}: no `{m}`" for m in markers if m not in source]
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
    print("ok: nothing to do, the overlay is already in place" if changed == 0 else f"ok: {changed} file(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
