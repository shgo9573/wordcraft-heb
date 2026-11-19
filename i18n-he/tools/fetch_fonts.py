#!/usr/bin/env python3
"""The Hebrew fonts this fork adds to the build: well-known families with Hebrew letters, fetched
into the craft-fonts checkout `crates/fonts/build.rs` embeds from (`CRAFT_FONTS_DIR`).

    python3 i18n-he/tools/fetch_fonts.py --into /path/to/craft-fonts
    python3 i18n-he/tools/fetch_fonts.py --list
    python3 i18n-he/tools/fetch_fonts.py --check --into /path/to/craft-fonts

Why this exists: craft-fonts ships one Hebrew face (Noto Sans Hebrew) and Word's own Hebrew fonts —
David, FrankRuhl, Miriam, Narkisim — are not free to redistribute. These are their OFL
equivalents, and the popular free Hebrew families beside them, so a Hebrew document written in this
fork has something to be written in:

  David Libre        David's shape (Word's default Hebrew document font)
  Frank Ruhl Libre   FrankRuhl's shape (Word's Hebrew serif)
  Miriam Libre       Miriam's shape (Word's Hebrew sans)
  Noto Serif Hebrew  Noto's serif companion to craft-fonts' Noto Sans Hebrew
  Heebo, Rubik, Assistant, Alef, Secular One, Suez One   the popular free Hebrew families
  Arimo, Cousine     Arial's and Courier New's metrics, both with Hebrew letters

Each is embedded on every build (the daily sync included) by adding it to the craft-fonts
checkout's `fonts/manifest.txt`, which is the file `build.rs` reads — nothing is committed here.
The files come from google/fonts at a pinned commit (`GOOGLE_FONTS_REF`), through the GitHub API
(one file each; the repository's tarball is hundreds of megabytes), and every file is checked
against its SHA-256 before it is written, so a changed upstream file fails the build instead of
changing what is embedded.

The licences travel with the fonts: each directory gets its `OFL.txt`, and the packages copy them
(`packaging/env.sh`'s `copy_font_licences`). `--check` fails when a font is missing, wrong or not in
the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The commit of google/fonts the files come from: pinned here, with their hashes below, so the same
# source tree is fetched on every run.
GOOGLE_FONTS_REF = "cc5661d43cd4f9aad5567033a8e15ca28dc35c86"
FONTS_REPO = "google/fonts"
# „אדם” (Alef, Dalet, Mem): every file is checked for these before a build embeds it, so a family
# whose Hebrew is not there — a sha256 that was recorded for the wrong file, a name that points at
# a Latin-only sibling — fails here rather than in a menu full of boxes.
HEBREW_PROBE = "\u05d0\u05d3\u05dd"


@dataclass(frozen=True)
class Font:
    """One file to embed: its family, its style, where it goes, and where it comes from."""

    family: str
    style: str
    directory: str
    """The folder in the craft-fonts checkout (`fonts/<directory>/`)."""
    path: str
    """The file's path in google/fonts."""
    sha256: str
    licence_path: str
    licence_sha256: str
    scripts: str = "Hebr,Latn"
    licence: str = "OFL-1.1"

    @property
    def file_name(self) -> str:
        return self.path.rsplit("/", 1)[-1].replace("%5B", "[").replace("%5D", "]").replace("%2C", ",")

    @property
    def relative(self) -> str:
        return f"fonts/{self.directory}/{self.file_name}"

    @property
    def licence_relative(self) -> str:
        return f"fonts/{self.directory}/OFL.txt"

    @property
    def source(self) -> str:
        return f"https://github.com/{FONTS_REPO}/tree/{GOOGLE_FONTS_REF}/{self.path.rsplit('/', 1)[0]}"

    def manifest_line(self) -> str:
        fields = [self.family, self.style, self.relative, self.scripts, self.licence, self.licence_relative, self.sha256, self.source]
        return " | ".join(fields)


FONTS: list[Font] = [
    # Word's Hebrew document fonts' free equivalents.
    Font("David Libre", "Regular", "hebrew-david-libre", "ofl/davidlibre/DavidLibre-Regular.ttf",
         "923f06e0f6dc84e1649d8cc5d5e12a8d663adf6aba83ba15baa5d559fb47b86e",
         "ofl/davidlibre/OFL.txt", "01f227b494c348ca8daeeaecbb1e08988b222673ca4bdad1681e49ba4cc8a592"),
    Font("David Libre", "Medium", "hebrew-david-libre", "ofl/davidlibre/DavidLibre-Medium.ttf",
         "fa3e35197472768520a489b77009b75bfc55601f61a0c4d0c1b23ca7f87701ce",
         "ofl/davidlibre/OFL.txt", "01f227b494c348ca8daeeaecbb1e08988b222673ca4bdad1681e49ba4cc8a592"),
    Font("David Libre", "Bold", "hebrew-david-libre", "ofl/davidlibre/DavidLibre-Bold.ttf",
         "7610819c7888c8e7ecdfc573089113ec5355cf95078614ae0e30b509b05468f8",
         "ofl/davidlibre/OFL.txt", "01f227b494c348ca8daeeaecbb1e08988b222673ca4bdad1681e49ba4cc8a592"),
    Font("Frank Ruhl Libre", "Regular", "hebrew-frank-ruhl-libre", "ofl/frankruhllibre/FrankRuhlLibre%5Bwght%5D.ttf",
         "f9bf26966681037aae894b031bd0dcf2c1bfdfa128dd0640cf276fe62a338a43",
         "ofl/frankruhllibre/OFL.txt", "4e9720b2544d946737e7dfe0027a62c23c7247f0144f08bc437cdcc2e6a7d828"),
    Font("Miriam Libre", "Regular", "hebrew-miriam-libre", "ofl/miriamlibre/MiriamLibre%5Bwght%5D.ttf",
         "9ea850118d552d25e1fb8242cbd429a5801c691b6ce218458e1a039045114bb8",
         "ofl/miriamlibre/OFL.txt", "0cd2b9542857599d480b54cf372a86b523bc5ff683307029f129e1c161360d52"),
    Font("Noto Serif Hebrew", "Regular", "hebrew-noto-serif", "ofl/notoserifhebrew/NotoSerifHebrew%5Bwdth,wght%5D.ttf",
         "93caef921360788dc3b0e32136bb26f16bc57717ec482d48fc7fd43820617165",
         "ofl/notoserifhebrew/OFL.txt", "9b9fe028b5ba74d231659a1bbaf0ed09b11e759d1ca6a070999e16d151616b47"),
    # The popular free Hebrew families.
    Font("Heebo", "Regular", "hebrew-heebo", "ofl/heebo/Heebo%5Bwght%5D.ttf",
         "18f930b583fa8fe6b40b2f8263b7ac6afbac07adc91a12467874e7467d3ace30",
         "ofl/heebo/OFL.txt", "866747cbccae229433e946b90fcfc457b81c33ac89e593855770851354f9e6c3"),
    Font("Rubik", "Regular", "hebrew-rubik", "ofl/rubik/Rubik%5Bwght%5D.ttf",
         "1b3a7437ba2af80e465e773ed60c5036d1ba6ace492d89046dbcf18fb31e4e88",
         "ofl/rubik/OFL.txt", "472cbe7c25441df63e9c7864b43eb3c0f4b3df950c66a76224e6cfe1eae843fb"),
    Font("Assistant", "Regular", "hebrew-assistant", "ofl/assistant/Assistant%5Bwght%5D.ttf",
         "1c3b393884f8fb133a1b17f41d26178adae1050a4f86d7a429d1b5658c314fa3",
         "ofl/assistant/OFL.txt", "7eaf6282cfab122b99ffd62a122fc27b6c3c8f2c65b56ff9b3a25badbc64887d"),
    Font("Alef", "Regular", "hebrew-alef", "ofl/alef/Alef-Regular.ttf",
         "a32adcc953ac356906901778460083dc207d4560cb586fd9ea24ec5b186969ed",
         "ofl/alef/OFL.txt", "c267a00c9476c78a2336d7b372b536885b8b24173a29ed53496f67a742c14961"),
    Font("Alef", "Bold", "hebrew-alef", "ofl/alef/Alef-Bold.ttf",
         "5dae0d7b2365288d8a34f5fb033d4278be96cef2547862cb93ceb8373e10bcf1",
         "ofl/alef/OFL.txt", "c267a00c9476c78a2336d7b372b536885b8b24173a29ed53496f67a742c14961"),
    Font("Secular One", "Regular", "hebrew-secular-one", "ofl/secularone/SecularOne-Regular.ttf",
         "2f45092a521db5042887941edfef73178ed7c5ba7fdfc5b6f581d44aab7b0234",
         "ofl/secularone/OFL.txt", "0b27313ffedb61d9941c5ba17c8b9ef5d2724c6e9aff41cd1ece24baed059eae"),
    Font("Suez One", "Regular", "hebrew-suez-one", "ofl/suezone/SuezOne-Regular.ttf",
         "3ef86844aad0cf9db7dcbda326f3d2f54cc4ccfe56db949e9e0c60a17031bd41",
         "ofl/suezone/OFL.txt", "aa8a8196a3e22c3bd985e33cd3245ae9a38accba5e79fc0e3b292612a8d6b337"),
    # Arial's and Courier New's metrics, with Hebrew letters: a document that names them can be
    # written and laid out here without a copy of Arial.
    Font("Arimo", "Regular", "hebrew-arimo", "ofl/arimo/Arimo%5Bwght%5D.ttf",
         "e43898b143ec826ac8cb4034816458a7047fbe0836558de2a1f8c6223ae3e0ca",
         "ofl/arimo/OFL.txt", "11cce536cd2f3864d767003af5dcd739e2e15818cf2279b6175edeadd3960992"),
    Font("Cousine", "Regular", "hebrew-cousine", "ofl/cousine/Cousine-Regular.ttf",
         "1da22250675fc4c42fcf3a9736c44bc0570516105331443b663fd5cfbd1412fe",
         "ofl/cousine/OFL.txt", "b81c4d4dc0a9f72c9155e78187316e016e2012a8102468804173dc61468b906d"),
]

MANIFEST_HEADER = "fonts/manifest.txt"


def api_url(path: str) -> str:
    """The GitHub API URL of one file of the pinned google/fonts commit."""
    return f"https://api.github.com/repos/{FONTS_REPO}/contents/{path}?ref={GOOGLE_FONTS_REF}"


def download(path: str) -> bytes:
    """One file of google/fonts, raw: the contents API serves it for this commit."""
    request = urllib.request.Request(api_url(path), headers={"Accept": "application/vnd.github.raw", "User-Agent": "wordcraft-heb-fetch-fonts"})
    # A token (the workflow's) only lifts the API's rate limit; the files are public.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"error: {path}: HTTP {e.code} from the GitHub API") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"error: {path}: {e.reason}") from None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def covers_hebrew(data: bytes) -> bool:
    """Does this font file's character map hold [`HEBREW_PROBE`]? A small `cmap` reader: the
    Unicode subtable (format 12, else format 4) is the list of characters a font can draw."""
    def u16(at: int) -> int:
        return struct.unpack(">H", data[at : at + 2])[0]

    def u32(at: int) -> int:
        return struct.unpack(">I", data[at : at + 4])[0]

    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return False
    tables: dict[str, int] = {}
    for i in range(u16(4)):
        at = 12 + 16 * i
        tables[data[at : at + 4].decode("latin-1")] = u32(at + 8)
    if "cmap" not in tables:
        return False
    start = tables["cmap"]
    sub12 = sub4 = None
    for i in range(u16(start + 2)):
        record = start + 4 + 8 * i
        sub = start + u32(record + 4)
        match u16(sub):
            case 12 if sub12 is None:
                sub12 = sub
            case 4 if sub4 is None:
                sub4 = sub
    ranges: list[tuple[int, int]] = []
    if sub12 is not None:
        for g in range(u32(sub12 + 12)):
            at = sub12 + 16 + 12 * g
            ranges.append((u32(at), u32(at + 4)))
    elif sub4 is not None:
        segments = u16(sub4 + 6) // 2
        ends = [u16(sub4 + 14 + 2 * s) for s in range(segments)]
        starts = [u16(sub4 + 16 + 2 * segments + 2 * s) for s in range(segments)]
        ranges = [(s, e) for s, e in zip(starts, ends) if s != 0xFFFF]
    else:
        return False
    return all(any(low <= ord(c) <= high for low, high in ranges) for c in HEBREW_PROBE)


def install(font: Font, into: Path, check: bool, problems: list[str]) -> bool:
    """Fetch (or check) one font file and its licence. Returns whether it wrote anything."""
    for relative, path, expected in ((font.relative, font.path, font.sha256), (font.licence_relative, font.licence_path, font.licence_sha256)):
        target = into / relative
        if target.exists() and sha256_of(target.read_bytes()) == expected:
            data = target.read_bytes()
            if relative.endswith(".ttf") and not covers_hebrew(data):
                problems.append(f"{relative}: the file draws none of {HEBREW_PROBE!r}, so it is not a Hebrew face")
            continue
        if check:
            problems.append(f"{relative}: missing or not the pinned file (expected sha256 {expected[:12]}…)")
            continue
        data = download(path)
        got = sha256_of(data)
        if got != expected:
            raise SystemExit(f"error: {path}: sha256 {got} is not the pinned {expected}: google/fonts changed under {GOOGLE_FONTS_REF}")
        if relative.endswith(".ttf") and not covers_hebrew(data):
            raise SystemExit(f"error: {path}: the file draws none of {HEBREW_PROBE!r}, so it is not a Hebrew face")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"{relative}: fetched ({len(data)} bytes)")
    return True


def add_to_manifest(font: Font, into: Path, check: bool, problems: list[str]) -> None:
    manifest = into / MANIFEST_HEADER
    line = font.manifest_line()
    if not manifest.exists():
        if check:
            problems.append(f"{MANIFEST_HEADER}: missing (the build reads the manifest from the craft-fonts checkout)")
        elif not into.is_dir():
            raise SystemExit(f"error: {into} is not a directory: point --into at a craft-fonts checkout")
        else:
            raise SystemExit(f"error: {into} has no {MANIFEST_HEADER}: is it a craft-fonts checkout?")
        return
    text = manifest.read_text(encoding="utf-8")
    if font.relative in text:
        if check and line not in text:
            problems.append(f"{MANIFEST_HEADER}: {font.relative} is listed, but not with this fork's line")
        return
    if check:
        problems.append(f"{MANIFEST_HEADER}: {font.relative} is not listed")
        return
    if not text.endswith("\n"):
        text += "\n"
    manifest.write_text(text + line + "\n", encoding="utf-8", newline="\n")
    print(f"{MANIFEST_HEADER}: added {font.family} {font.style}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--into", type=Path, help="a storytold/craft-fonts checkout (its fonts/ gets the files)")
    parser.add_argument("--list", action="store_true", help="print the fonts and their sources, without fetching")
    parser.add_argument("--check", action="store_true", help="report what is missing instead of fetching")
    args = parser.parse_args()

    if args.list or (not args.into and not args.check):
        # The table itself, checked: a manifest line is eight ` | `-separated fields (the format
        # `crates/fonts/build.rs` reads), a path is listed once, and every file has a licence.
        problems: list[str] = []
        seen: set[str] = set()
        for font in FONTS:
            if font.relative in seen:
                problems.append(f"{font.relative}: listed twice")
            seen.add(font.relative)
            if len(font.manifest_line().split(" | ")) != 8:
                problems.append(f"{font.family} {font.style}: the manifest line is not eight fields")
            if len(font.sha256) != 64 or len(font.licence_sha256) != 64:
                problems.append(f"{font.relative}: a sha256 is not 64 hex digits")
            for value in (font.sha256, font.licence_sha256):
                if any(c not in "0123456789abcdef" for c in value):
                    problems.append(f"{font.relative}: a sha256 is not lowercase hex")
            print(f"{font.family} {font.style}\t{font.relative}\t{font.source}")
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if problems:
            return 1
        families = sorted({font.family for font in FONTS})
        print(f"\n{len(FONTS)} file(s), {len(families)} families: {', '.join(families)}", file=sys.stderr)
        return 0

    if not args.into:
        parser.error("--into is required to fetch or check")

    problems: list[str] = []
    for font in FONTS:
        install(font, args.into, args.check, problems)
        add_to_manifest(font, args.into, args.check, problems)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    families = sorted({font.family for font in FONTS})
    if args.check:
        print(f"ok: {len(FONTS)} Hebrew font file(s) from {len(families)} families are in {args.into}")
    else:
        print(f"ok: {len(families)} Hebrew font families are in {args.into}: {', '.join(families)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
