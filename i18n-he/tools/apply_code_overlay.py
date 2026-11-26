#!/usr/bin/env python3
"""Apply this fork's Hebrew code changes to a checkout of upstream, idempotently.

The Hebrew catalog itself is data (`i18n-he/locales/he/`), but offering it needs four small code
changes: the `he` row in `LANGUAGES`, a public `Lang::catalog_texts`, the interface font fallback
for scripts Inter lacks (`theme::interface_char_covered`, `theme::faces_for_interface_text`) and
its call in `install_ui_fonts`. (Upstream mirrors a right-to-left interface itself, so Hebrew needs
no layout code of its own; only the rows a mirror does not fix are in the table.) They are committed in this fork; upstream's daily merge rewrites
the same files, so after a conflict the workflow takes upstream's version and re-applies them with
this script. Running it on a tree that already has them changes nothing.

    python3 i18n-he/tools/apply_code_overlay.py            # apply
    python3 i18n-he/tools/apply_code_overlay.py --check    # only report what is missing

The rest of the fork's code is larger: `code-overlay.json` lists, per upstream file, the exact
upstream text a change replaces (or the line it goes after) and the text it becomes, and `code/`
holds the files this fork adds whole — Hebrew proofing, `crates/proof-he/`, which upstream's
`craft-proof` has no language for. `--check` also reports when a copy in `code/` has drifted from
the file it mirrors.

A change whose base text this tree no longer has is reported as a warning and skipped: a merge
that restructures a file (the UI ported onto craft, #7101) leaves recorded changes that cannot land,
and the sync prunes them from the table (`record_code_overlay.py --prune`) while it still applies the
ones that can. An entry written for one layout of the UI says so (`"layouts": ["prefs"]` or
`["ui_state"]`), so one table serves a merge across the change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from code_match import applied, candidates, has_code  # noqa: E402  (the sibling matcher)

HE_ROW = '''    // Hebrew, right to left; `he`, `he-IL` and `he_IL.UTF-8` resolve here. Its catalog is this
    // fork's (`i18n-he/`, laid over craft-i18n by `i18n-he/tools/assemble.py`), not
    // storytold/craft-i18n's: it is embedded whenever that overlay is in `CRAFT_I18N_DIR`. The
    // interface mirrors right to left ([`RTL_LANGUAGES`]), and WordCraft proofs
    // Hebrew (`wordcraft_proof_he`), so new documents are written in Hebrew.
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

# Upstream's own doc comment over `the_languages_offered_are_the_embedded_ones_of_the_list`
# (upstream #7101): the same place `offers_hebrew` goes when the first anchor is gone.
TESTS_HELPER_ANCHOR_2 = "/// WordCraft offers exactly the languages in `LANGUAGES` when craft-i18n is embedded, and English"

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

# The Hebrew proofer is a crate of its own, and the workspace has to know it. Anchored on the table
# header rather than on a line of upstream's: every line around it is a craft-libs `rev`, which
# upstream bumps on its own schedule, and a recorded change that quotes one goes stale with it.
CARGO_ANCHOR = "[workspace.dependencies]\n"

CARGO_LINES = '''# This fork's Hebrew proofing — spelling, suggestions and grammar — beside craft-proof, which has
# every other language (its `ProofLang` has no Hebrew). See `crates/proof-he`.
wordcraft-proof-he = { path = "crates/proof-he" }
'''


def apply_cargo(source: str) -> tuple[str, list[str]]:
    if 'wordcraft-proof-he = { path = "crates/proof-he" }' in source:
        return source, []
    if CARGO_ANCHOR not in source:
        raise SystemExit("error: Cargo.toml has no `[workspace.dependencies]`")
    return source.replace(CARGO_ANCHOR, CARGO_ANCHOR + CARGO_LINES, 1), ["Cargo.toml: the Hebrew proofer is a workspace member"]


FONTS_ANCHOR = "        let mut faces = self.canvas.ime_faces.clone();\n"

# Upstream's `apply_ui_fonts` builds the face list without the language it installs for (it is
# called from the composition path as well, where there is no language to hand), so the Hebrew
# faces come from the interface language the app is drawing in.
FONTS_LINES = '''        // Interface text in a script the interface faces leave out (Hebrew, Arabic, Thai …)
        // borrows a document face, as the caption does: the Hebrew menus, dialogs and the
        // language picker would otherwise draw as boxes. Looked at again only when the fonts
        // are installed, that is when the language changes.
        //
        // Every language's own name, not just this one's: File ▸ Options lists them all, so a
        // Hebrew interface (the default) shows „עברית” in that list before Hebrew is the
        // current language — and after switching away from it.
        let names = i18n::Lang::all().map(i18n::Lang::name);
        faces.extend(theme::faces_for_interface_text(crate::i18n::current().catalog_texts().chain(names)));
'''


def missing_he_row(source: str) -> bool:
    return 'code: "he"' not in source


HE_ROW_ANY = re.compile(r'    // Hebrew, right to left;.*?\n(?:    //.*?\n)*    LangInfo \{ code: "he", prefer_hans: false, editing_lang: [^}]*\},\n', re.S)


def apply_i18n(source: str, root: Path) -> tuple[str, list[str]]:
    """The `he` row in `LANGUAGES` and the public `catalog_texts`."""
    notes: list[str] = []
    row = HE_ROW
    if not missing_he_row(source) and row not in source:
        # A row the earlier overlay wrote (it said the interface stays left to right): bring it up
        # to date, since the row now carries the Hebrew editing language.
        source, count = HE_ROW_ANY.subn(row, source, count=1)
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
        source = source[: end + 1] + row + source[end + 1 :]
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


# Upstream's theme module is one file until #7101 and `theme.rs` + `theme/legacy.rs` after it. The
# document faces this fork asks for the interface belong beside `faces_for_preedit`, wherever that
# is: the anchor decides the file, so a sync across the split keeps working.
THEME_FILES = ["crates/ui-egui/src/theme.rs", "crates/ui-egui/src/theme/legacy.rs"]


def theme_file(root: Path) -> Path:
    """The file holding `faces_for_preedit`: where the interface fallback's helpers go."""
    for relative in THEME_FILES:
        path = root / relative
        if path.is_file() and THEME_ANCHOR in path.read_text(encoding="utf-8"):
            return path
    raise SystemExit(
        "error: no theme file has the anchor for the interface fallback "
        f"({THEME_ANCHOR!r}): looked in {', '.join(THEME_FILES)}"
    )


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
    helper = next((a for a in (TESTS_HELPER_ANCHOR, TESTS_HELPER_ANCHOR_2) if a in source), None)
    if helper is None:
        raise SystemExit("error: i18n/tests.rs has no anchor for `offers_hebrew`")
    source = source.replace(helper, TESTS_HELPER + helper, 1)
    if TESTS_AVAILABLE not in source:
        raise SystemExit("error: i18n/tests.rs has no `available` length assertion")
    source = source.replace(TESTS_AVAILABLE, TESTS_AVAILABLE_PATCHED, 1)
    if TESTS_LISTED not in source:
        raise SystemExit("error: i18n/tests.rs has no `the_languages_offered_are_the_embedded_ones_of_the_list` body")
    source = source.replace(TESTS_LISTED, TESTS_LISTED_PATCHED, 1)
    notes.append("i18n/tests.rs: the offered languages count with the overlay")
    return source, notes


def apply_fonts(source: str) -> tuple[str, list[str]]:
    """The interface's faces borrow the document faces Hebrew needs — as far as it still applies.

    Upstream #7101 moved the interface's font installation onto the craft framework's own stack
    (`ui_fonts`/`OnDemandFonts`), and the line this fork appends to is gone with it: there is no
    list here any more to borrow a face for. That is reported as a note, not a failure — a daily
    sync must not stop on it — and the missing Hebrew menus of that layout are the next thing this
    fork's README lists as outstanding.
    """
    if "faces_for_interface_text" in source:
        return source, []
    if FONTS_ANCHOR not in source:
        print("warning: app/fonts.rs has no line to borrow document faces for the interface text "
              "(the interface's fonts moved to craft; Hebrew interface text may need a system face)")
        return source, []
    return source.replace(FONTS_ANCHOR, FONTS_ANCHOR + FONTS_LINES, 1), ["app/fonts.rs: borrow document faces for the interface text"]


# ---------------------------------------------------------------------------------------------
# The layout upstream has after #7101 (the UI ported onto the craft framework): `UiState` became
# `Prefs`, the app loads it in `WordApp::apply_prefs` (`crates/ui-egui/src/app/prefs.rs`) instead of
# in `apps/wordcraft/src/main.rs`, and the module that spells the fallback faces out changed.
# Each change below is written for that layout only, and is a no-op on the older one.
# ---------------------------------------------------------------------------------------------

DEFAULT_LANGUAGE_DOC = """/// The interface language this fork opens in: Hebrew. A new profile, and every settings file that
/// never chose a language, shows Hebrew — which is what this fork exists for. File ▸ Options ▸
/// Interface language lists every other language beside it, `Automatic` (the system's language)
/// among them, and a choice there is what the app keeps from then on.
pub const DEFAULT_LANGUAGE: &str = "he";

"""

# `Prefs` is built by `serde` with `#[serde(default)]`, so a new field needs only its own default,
# and an old `ui.json` reads as "never chose a language".
PREFS_FIELDS = """    /// Has an interface language been chosen (File ▸ Options ▸ Interface language, or the
    /// `ui.language` command)? `false` for a settings file written before this field, whose
    /// `language` is `auto` whether or not anyone wanted the system's language — so it opens in
    /// Hebrew (see [`WordApp::apply_prefs`]).
    pub language_chosen: bool,
"""

PREFS_ADOPT = """        // This fork opens in Hebrew: a settings file that never chose an interface language
        // moves to it here, when the app loads its preferences (`i18n::DEFAULT_LANGUAGE`).
        if !self.ui.language_chosen && self.ui.language.eq_ignore_ascii_case(crate::i18n::AUTO) {
            self.ui.language = crate::i18n::DEFAULT_LANGUAGE.to_string();
        }
"""


def apply_prefs(source: str) -> tuple[str, list[str]]:
    """Hebrew as the language a settings file that never chose one opens in.

    On the `Prefs` layout the field is declared in `crates/ui-egui/src/prefs.rs` and the default it
    needs comes from `#[serde(default)]` (`PREFS_FIELDS`); the choice is made in `apply_prefs`,
    which the app runs for every settings file it opens (`with_settings`, the host's own load). The
    older `UiState` layout gets both from `apps/wordcraft/src/main.rs` and
    `crates/ui-egui/src/lib.rs` instead (`code-overlay.json`), and this does nothing there.
    """
    notes: list[str] = []
    anchor = "    pub language: String,\n"
    if "language_chosen" not in source and anchor in source:
        source = source.replace(anchor, anchor + PREFS_FIELDS, 1)
        notes.append("prefs.rs: `language_chosen` (did anyone choose an interface language?)")
    # `Prefs::default` is one struct literal, every field named: the new one has to be there too.
    initial = "            language: i18n::AUTO.into(),\n"
    if "            language_chosen: false,\n" not in source and initial in source:
        source = source.replace(initial, initial + "            language_chosen: false,\n", 1)
        notes.append("prefs.rs: its default (no language chosen)")
    return source, notes


def apply_apply_prefs(source: str) -> tuple[str, list[str]]:
    """Hebrew for a settings file that never chose a language, in `WordApp::apply_prefs`."""
    if "DEFAULT_LANGUAGE" in source:
        return source, []
    anchor = "    pub fn apply_prefs(&mut self, ui: Prefs) {\n"
    if anchor not in source:
        return source, []
    body = "        self.ui = ui;\n"
    at = source.find(anchor)
    end = source.find(body, at)
    if end < 0:
        return source, []
    end += len(body)
    return source[:end] + PREFS_ADOPT + source[end:], ["app/prefs.rs: a profile that never chose opens in Hebrew"]


def apply_default_language(source: str) -> tuple[str, list[str]]:
    """`DEFAULT_LANGUAGE`, `Lang::rtl`'s Hebrew row, and the right-to-left list, on either layout."""
    notes: list[str] = []
    if "pub const DEFAULT_LANGUAGE" not in source:
        anchor = 'pub const AUTO: &str = "auto";\n'
        if anchor in source:
            source = source.replace(anchor, anchor + DEFAULT_LANGUAGE_DOC, 1)
            notes.append("i18n.rs: `DEFAULT_LANGUAGE` (Hebrew)")
    if 'const RTL_LANGUAGES: [&str; 2] = ["ar", "he"];' not in source:
        for old, new in (
            ('const RTL_LANGUAGES: [&str; 1] = ["ar"];', 'const RTL_LANGUAGES: [&str; 2] = ["ar", "he"];'),
            ('const RTL_LANGUAGES: &[&str] = &["ar"];', 'const RTL_LANGUAGES: &[&str] = &["ar", "he"];'),
        ):
            if old in source:
                source = source.replace(old, new, 1)
                notes.append("i18n.rs: Hebrew is right to left (`RTL_LANGUAGES`)")
                break
    return source, notes


GITATTRIBUTES_LINES = """# The Hebrew catalogs are TAB-separated: LF everywhere, so a Windows checkout writes the same bytes.
i18n-he/** text eol=lf
"""


def apply_gitattributes(source: str) -> tuple[str, list[str]]:
    """This fork's `.gitattributes` lines, appended to whatever upstream's file says.

    Upstream added a `* text=auto` block of its own (and `craft-i18n.rev text eol=lf`, which this
    fork had): both sides edit the same few lines, so a merge conflicts there. Taking upstream's
    file and appending our line keeps both.
    """
    if "i18n-he/** text eol=lf" in source:
        return source, []
    if source and not source.endswith("\n"):
        source += "\n"
    return source + GITATTRIBUTES_LINES, [".gitattributes: the Hebrew catalogs are LF"]


def locate(source: str, text: str, name: str, what: str, anchor: bool = False) -> tuple[int, int] | None:
    """Where `source` has `text`, or None; SystemExit when it has it more than once."""
    where = candidates(source, text, anchor)
    if len(where) > 1:
        raise SystemExit(f"error: {name} has the text a Hebrew change {what} {len(where)} times:\n{text.strip().splitlines()[0][:70]}")
    return where[0] if where else None


def _skipped(name: str, hunk: dict, why: str) -> None:
    """A change this layout cannot take: said once, in the log, and the sync goes on."""
    wanted = (hunk.get("insert") or hunk.get("new") or hunk.get("old") or "").strip().splitlines()
    print(f"warning: {name}: skipped a Hebrew change ({why}): {wanted[0][:70] if wanted else '?'}")


# The type the older layout spelled its UI state with. Upstream #7101 replaced it with `Prefs`
# (`crates/ui-egui/src/prefs.rs`), and a table entry written for a layout says so:
#
#   "layouts": ["prefs"]       only where the tree has `Prefs` (after #7101)
#   "layouts": ["ui_state"]    only where it has `UiState` (before it)
#
# An entry without the key fits both. A hunk may carry `insert_legacy` or `new_legacy` instead: the
# same change written for the older layout, chosen per tree.
LEGACY_MARKER = "UiState"


def for_layout(hunks: list[dict], legacy: bool) -> list[dict]:
    """The hunks written for the layout this tree is in (`legacy` = it still has [`LEGACY_MARKER`])."""
    here = "ui_state" if legacy else "prefs"
    chosen: list[dict] = []
    for hunk in hunks:
        if "layouts" in hunk:
            if here not in hunk["layouts"]:
                continue
            hunk = {k: v for k, v in hunk.items() if k != "layouts"}
        if not legacy and "insert_legacy" in hunk:
            hunk = {k: v for k, v in hunk.items() if k != "insert_legacy"}
        elif not legacy and "new_legacy" in hunk:
            hunk = {k: v for k, v in hunk.items() if k != "new_legacy"}
        elif legacy and "insert_legacy" in hunk:
            hunk = {**{k: v for k, v in hunk.items() if k not in ("insert", "insert_legacy")}, "insert": hunk["insert_legacy"]}
        elif legacy and "new_legacy" in hunk:
            hunk = {**{k: v for k, v in hunk.items() if k not in ("new", "new_legacy")}, "new": hunk["new_legacy"]}
        chosen.append(hunk)
    return chosen


def has_legacy_layout(root: Path) -> bool:
    """Does the tree still declare [`LEGACY_MARKER`] (`crates/ui-egui/src/lib.rs` before #7101)?"""
    lib = root / "crates/ui-egui/src/lib.rs"
    return lib.exists() and "pub struct UiState" in lib.read_text(encoding="utf-8")


def apply_i18n_here(source: str) -> tuple[str, list[str]]:
    """`apply_i18n` for the tree this script is in (its `root` is a few lines down in `main`)."""
    return apply_i18n(source, Path(__file__).resolve().parents[2])


def apply_hunks(source: str, hunks: list[dict], name: str) -> tuple[str, list[str]]:
    """The edits `code-overlay.json` lists for a file, idempotently.

    A hunk replaces `old` with `new`, or inserts `insert` after the line `after`. A hunk already
    applied is skipped ([`applied`]), so running this on this fork's own tree changes nothing —
    however that tree is formatted ([`locate`]).
    """
    notes: list[str] = []
    for hunk in hunks:
        if applied(source, hunk):
            continue
        if "insert" in hunk:
            found = locate(source, hunk["after"], name, "follows", anchor=True)
            if found is None:
                _skipped(name, hunk, "the line it follows is gone")
                continue
            _, end = found
            # Right after the anchor line; a code match stops at its last character, before the
            # line break the anchor's text had.
            at = end
            if source[end - 1 : end] != "\n":
                line_end = source.find("\n", end)
                at = end if line_end == -1 else line_end + 1
            source = source[:at] + hunk["insert"] + source[at:]
        elif not hunk["new"]:
            found = locate(source, hunk["old"], name, "removes")
            if found is None:
                continue
            source = _drop_line(source, *found)
            notes.append(f"{name}: removed {hunk['old'].strip().splitlines()[0][:60]}")
            continue
        else:
            found = locate(source, hunk["old"], name, "replaces")
            if found is None:
                _skipped(name, hunk, "the text it replaces is gone")
                continue
            start, end = found
            source = source[:start] + _keep_break(source, end, hunk["new"]) + source[end:]
        first = next((line.strip() for line in hunk.get("insert", hunk.get("new", "")).splitlines() if line.strip()), "")
        notes.append(f"{name}: {first[:70]}")
    return source, notes


def _keep_break(source: str, end: int, new: str) -> str:
    """`new`, without adding a line break the source already has where the old text ended.

    Only when the match stopped *before* the line's own break: a code match may end at the last
    character, leaving `source[end]` to supply it. Once the match includes the break, a newline at
    `source[end]` is the next line's — often the blank line after the one replaced — and dropping
    `new`'s break for it silently swallowed that blank line (a recorded replacement of the
    `portable.zip` line in `packaging/windows/package.ps1` did, and the doc paragraph below it ran
    into the table).
    """
    if not new.endswith("\n"):
        return new
    if source[end - 1 : end] != "\n" and source[end : end + 1] == "\n":
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
    if not path.exists():
        # Upstream removed the file (its code moved or went away). The recorded changes cannot land
        # there any more; `prune_code_overlay.py` drops them from the table, and until it runs the
        # sync reports the file once rather than stopping on it.
        print(f"warning: {name}: upstream removed this file; its {len(hunks)} recorded Hebrew change(s) are stale")
        return "", []
    source = path.read_text(encoding="utf-8")
    return apply_hunks(source, for_layout(hunks, has_legacy_layout(root)), name)


def voice_patch_file(relative: Path) -> bool:
    """A file `i18n-he/tools/dictate_patch.py` copies, not this overlay.

    Voice › Dictate is a patch of its own, applied after the overlay and allowed to fail, so this
    overlay neither copies its module nor misses it when the days' build goes without it.
    """
    return relative == Path("crates/ui-egui/src/dictate.rs")


def copy_new_files(root: Path, code: Path, check: bool, missing: list[str]) -> list[str]:
    """The files this fork adds whole: `code/crates/...` mirrors the tree's `crates/...`.

    Every file, whatever its suffix: a list of the ones that count would leave the next unlisted
    file out silently — which is how `packaging/windows/wordcraft-bundle.wxs` went missing from a
    sync and took the Setup.exe with it. `code/` is this fork's own directory; what it holds is what
    to copy.
    """
    notes: list[str] = []
    added = sorted(p for p in code.rglob("*") if p.is_file())
    for source in added:
        relative = source.relative_to(code)
        if voice_patch_file(relative):
            continue
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

    # The changes the Hebrew catalog alone needs, spelled out above.
    targets = {
        root / "Cargo.toml": (apply_cargo, ['wordcraft-proof-he = { path = "crates/proof-he" }']),
        root / "crates/ui-egui/src/i18n.rs": (apply_i18n_here, []),
        theme_file(root): (apply_theme, ["fn faces_for_interface_text", "fn interface_char_covered"]),
        # The `Prefs` layout upstream took in #7101: the same two changes, in the files that layout
        # declares and loads the state in. On the older layout `code-overlay.json` has them (the
        # `UiState` field and `apps/wordcraft/src/main.rs`), so this step is skipped there.
        root / "crates/ui-egui/src/prefs.rs": (apply_prefs, ["language_chosen"]),
        root / "crates/ui-egui/src/app/prefs.rs": (apply_apply_prefs, ["DEFAULT_LANGUAGE"]),
        # `apply_fonts` reports when the line it appends to is gone (upstream #7101), so this file
        # has no marker `--check` can insist on.
        root / "crates/ui-egui/src/app/fonts.rs": (apply_fonts, []),
        root / "crates/ui-egui/src/i18n/tests.rs": (apply_tests, ["fn offers_hebrew()"]),
        root / ".gitattributes": (apply_gitattributes, ["i18n-he/** text eol=lf"]),
    }
    # The `Prefs` files exist only after upstream #7101: on the older layout the same two changes
    # live in `apps/wordcraft/src/main.rs` and `crates/ui-egui/src/lib.rs` (`code-overlay.json`).
    targets = {path: step for path, step in targets.items() if path.exists()}
    # `app/prefs.rs` writes the `Prefs` half of the default language; on the `UiState` layout the
    # check for it is `apps/wordcraft/src/main.rs`'s recorded change, so this marker is asked for
    # only where `Prefs` is the state type.
    if has_legacy_layout(root):
        targets.pop(root / "crates/ui-egui/src/app/prefs.rs", None)
    # Everything the right-to-left interface and Hebrew proofing touch, checked against upstream's
    # exact text (`code-overlay.json`) plus the files this fork adds whole (`code/`).
    hunks: dict[str, list[dict]] = json.loads((root / "i18n-he/code-overlay.json").read_text(encoding="utf-8"))
    generics = {root / relative: patch for relative, patch in hunks.items()}
    code = root / "i18n-he/code"

    if args.files:
        # The workflow takes upstream's version of a conflicting one of these and runs the overlay
        # again, so the list has to come from the overlay itself, not a copy of it.
        paths = {path.relative_to(root) for path in list(targets) + list(generics)}
        paths |= {path.relative_to(code) for path in code.rglob("*") if path.suffix == ".rs" or path.name == "Cargo.toml"}
        for path in sorted(paths):
            print(path)
        return 0

    missing: list[str] = []
    if args.check:
        for path, (apply, markers) in targets.items():
            # What the file would hold once the overlay ran, so a step that has to spell its change
            # out (`apply_i18n`) is checked by its markers like the ones that only insert text.
            source = apply(path.read_text(encoding="utf-8"))[0]
            missing += [f"{path.relative_to(root)}: no `{m}`" for m in markers if m not in source]
        for path, patch in generics.items():
            source = path.read_text(encoding="utf-8") if path.exists() else ""
            for hunk in for_layout(patch, has_legacy_layout(root)) if path.exists() else patch:
                if not applied(source, hunk):
                    wanted = hunk.get("insert", hunk.get("new", hunk.get("old", "")))
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
        if path == root / "crates/ui-egui/src/i18n.rs":
            patched, more = apply_default_language(patched)
            notes += more
        if patched != source:
            path.write_text(patched, encoding="utf-8", newline="\n")
            changed += 1
        for note in notes:
            print(note)
    for path, patch in generics.items():
        if not path.exists():
            apply_generic(root, path, patch)
            continue
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
