#!/usr/bin/env python3
"""Turn a `cargo` log into the two things a browser-less maintainer can read: annotations and a
markdown report that a workflow posts on the pull request.

    cargo check --workspace --all-targets --message-format=short 2>&1 | tee cargo.log
    python3 i18n-he/tools/rust_failures.py --annotate cargo.log     # ::error file=…,line=…::…
    python3 i18n-he/tools/rust_failures.py --markdown cargo.log     # a comment body

`--message-format=short` writes one diagnostic per line (`path:line:col: error[E0425]: …`), which is
what is parsed here. The report keeps the errors, the file they are in and the lines around them,
and drops the dependency-build chatter that floods a first `cargo check`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `crates/proof/src/he/mod.rs:12:5: error[E0425]: cannot find value `x` in this scope`
DIAGNOSTIC = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?P<col>\d+): (?P<level>error|warning)(\[(?P<code>[A-Z]\d+)\])?: (?P<message>.*)$")
# A rustc error that has no location (`error: could not compile …`).
BARE = re.compile(r"^(?P<level>error|warning)(\[(?P<code>[A-Z]\d+)\])?: (?P<message>.*)$")
# The dependency build noise of a first check; never worth a report.
NOISE = re.compile(r"^\s*(Compiling|Checking|Finished|Downloaded|Downloading|Blocking|Updating|Adding|Locking|Unpacking)\b")
# A test failure (`---- name stdout ----`, `thread 'x' panicked at …`) or a doctest.
TEST_FAILURE = re.compile(r"^(---- .* ----|thread '.*' panicked|assertion .* failed|test result: FAILED)")

MAX_ANNOTATIONS = 10
MAX_REPORT_ERRORS = 40
CONTEXT = 4


def parse(lines: list[str]) -> tuple[list[dict], list[str]]:
    errors: list[dict] = []
    for number, line in enumerate(lines):
        match = DIAGNOSTIC.match(line)
        if match and match.group("level") == "error":
            errors.append({**match.groupdict(), "index": number, "text": line})
            continue
        match = BARE.match(line)
        if match and match.group("level") == "error":
            errors.append({**match.groupdict(), "file": None, "line": None, "col": None, "index": number, "text": line})
    return errors, lines


def annotation(error: dict) -> str:
    message = error["message"].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    if error["file"]:
        return f"::error file={error['file']},line={error['line']},col={error['col']}::{message}"
    return f"::error::{message}"


def markdown(errors: list[dict], lines: list[str], title: str) -> str:
    out = [f"## {title}", ""]
    if not errors:
        out += ["No rustc error line found; the log's tail:", "", "```", *[line.rstrip() for line in lines[-40:]], "```"]
        return "\n".join(out) + "\n"
    files = sorted({error["file"] for error in errors if error["file"]})
    out += [f"{len(errors)} error line(s) in {len(files)} file(s).", ""]
    shown: set[tuple[int, int]] = set()
    for error in errors[:MAX_REPORT_ERRORS]:
        if error["file"]:
            where = f"`{error['file']}:{error['line']}:{error['col']}`"
        else:
            where = "rustc"
        out.append(f"* {where} — {error['message']}")
        # The lines around an error explain it, once: the rest are one line each.
        if not error["file"]:
            continue
        start, end = max(0, error["index"] - CONTEXT), min(len(lines), error["index"] + CONTEXT + 1)
        if any(start < shown_end and shown_start < end for shown_start, shown_end in shown):
            continue
        shown.add((start, end))
        out += ["", "```", *[line.rstrip() for line in lines[start:end]], "```", ""]
    if len(errors) > MAX_REPORT_ERRORS:
        out += [f"…and {len(errors) - MAX_REPORT_ERRORS} more error line(s); the workflow run's log has them all.", ""]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="the cargo log to read (`-` for stdin)")
    parser.add_argument("--annotate", action="store_true", help="print GitHub annotations (the first ten errors)")
    parser.add_argument("--markdown", action="store_true", help="print a report a pull-request comment can hold")
    parser.add_argument("--title", default="The Rust check failed", help="the report's heading")
    args = parser.parse_args()

    text = sys.stdin.read() if args.log == "-" else Path(args.log).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    errors, lines = parse(lines)
    if args.markdown:
        sys.stdout.write(markdown(errors, lines, args.title))
        return 0
    shown = errors[:MAX_ANNOTATIONS]
    for error in shown:
        print(annotation(error))
    if len(errors) > len(shown):
        print(f"::warning::{len(errors)} error line(s); only {len(shown)} are shown here")
    if not errors:
        # Not a compiler error: a missing tool, a fetch that failed, a test that panicked. Say where.
        interesting = [line for line in lines if not NOISE.match(line)][-25:]
        for line in interesting:
            escaped = line.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error::{escaped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
