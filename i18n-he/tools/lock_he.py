#!/usr/bin/env python3
"""Keep `Cargo.lock` naming this fork's Hebrew proofer, after a merge with upstream.

`crates/proof-he` (`wordcraft-proof-he`) is a workspace member of this fork only, so upstream's
`Cargo.lock` has no entry for it and every merge that touches the lockfile conflicts. The Windows
package builds with `--locked` (`packaging/windows/package.ps1`), which stops at a lockfile that
does not know a member: "the lock file … needs to be updated but --locked was passed".

`--files` lists what the sync takes upstream's version of and fixes here; `--check` reports a
lockfile that needs a fix (the catalogs job runs it, so this never reaches a Windows build). Run
without a flag to fix the file in place:

    python3 i18n-he/tools/lock_he.py            # add what is missing
    python3 i18n-he/tools/lock_he.py --check    # report only
    python3 i18n-he/tools/lock_he.py --files    # the paths a sync resets

Only additions are made — this never resolves versions, which is Cargo's job. Everything it writes
is derived from the tree: the member's own manifest for its package name, version and dependencies,
and the other members' manifests for who depends on it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MEMBER = "wordcraft-proof-he"
MANIFEST = "crates/proof-he/Cargo.toml"
# The lockfile names packages, not the workspace's renamings: the manifest says `wordcraft-proof`,
# the package behind that name is craft-libs' `craft-proof` (`Cargo.toml`'s `[workspace.dependencies]`).
LOCK_NAMES = {"wordcraft-proof": "craft-proof", "log": "log"}


def workspace_version(root: Path) -> str:
    """`[workspace.package] version`."""
    section = False
    for line in (root / "Cargo.toml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped == "[workspace.package]"
            continue
        if section and stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"')
    raise SystemExit("error: Cargo.toml has no [workspace.package] version")


def member_deps(root: Path) -> list[str]:
    """The member's dependencies, by their lockfile (package) names, in sorted order."""
    names: list[str] = []
    section = ""
    for line in (root / MANIFEST).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if not stripped or stripped.startswith("#") or section != "[dependencies]":
            continue
        key = stripped.split("=", 1)[0].strip()
        names.append(LOCK_NAMES.get(key, key))
    return sorted(names)


def members_depending_on_it(root: Path) -> list[str]:
    """Every workspace manifest that names the member as a dependency, by its package name."""
    out: list[str] = []
    for manifest in sorted(list((root / "crates").glob("*/Cargo.toml")) + list((root / "apps").glob("*/Cargo.toml"))):
        if manifest == root / MANIFEST:
            continue
        text = manifest.read_text(encoding="utf-8")
        if re.search(rf"^{re.escape(MEMBER)}\s*=", text, re.M):
            name = re.search(r"^name\s*=\s*\"([^\"]+)\"", text, re.M)
            if not name:
                raise SystemExit(f"error: {manifest.relative_to(root)} has no package name")
            out.append(name.group(1))
    return sorted(out)


def package_block(lock: str, name: str) -> tuple[int, int] | None:
    """The byte span of `name`'s `[[package]]` block in `lock`."""
    start = lock.find(f'[[package]]\nname = "{name}"\n')
    if start < 0:
        return None
    end = lock.find("\n[[package]]", start + 1)
    return start, (len(lock) if end < 0 else end + 1)


def dep_lines(lock: str, name: str) -> list[str]:
    """The dependencies a lockfile entry lists, without quotes or commas."""
    span = package_block(lock, name)
    if span is None:
        return []
    block = lock[span[0] : span[1]]
    head = block.find("dependencies = [\n")
    if head < 0:
        return []
    tail = block.find("]\n", head)
    body = block[head + len("dependencies = [\n") : tail]
    return re.findall(r'"([^"]+)"', body)


def set_dep_lines(lock: str, name: str, deps: list[str]) -> str:
    """`name`'s entry with exactly `deps` as its dependencies, in Cargo's order (sorted)."""
    span = package_block(lock, name)
    if span is None:
        return lock
    block = lock[span[0] : span[1]]
    head = block.find("dependencies = [\n")
    if head < 0:
        return lock
    tail = block.find("]\n", head)
    listing = "".join(f' "{d}",\n' for d in sorted(set(deps)))
    block = block[: head + len("dependencies = [\n")] + listing + block[tail:]
    return lock[: span[0]] + block + lock[span[1] :]


def fix(lock: str, root: Path) -> tuple[str, list[str]]:
    """`lock` with the member, and everyone's edge to it, added; and what was added."""
    notes: list[str] = []
    version = workspace_version(root)
    if package_block(lock, MEMBER) is None:
        entry = f'[[package]]\nname = "{MEMBER}"\nversion = "{version}"\ndependencies = [\n'
        entry += "".join(f' "{d}",\n' for d in member_deps(root))
        entry += "]\n\n"
        # Cargo keeps the file alphabetical by package name: before the next `[[package]]` whose
        # name sorts after ours, and after the last one before it.
        names = [(m.start(), m.group(1)) for m in re.finditer(r'\[\[package\]\]\nname = "([^"]+)"\n', lock)]
        after = [start for start, name in names if name < MEMBER]
        at = len(lock)
        if after:
            at = max(after)
            at = lock.find("\n[[package]]", at) + 1 if lock.find("\n[[package]]", at) >= 0 else len(lock)
        lock = lock[:at] + entry + lock[at:]
        notes.append(f"Cargo.lock: {MEMBER} {version}")
    for member in members_depending_on_it(root):
        deps = dep_lines(lock, member)
        if not deps:
            continue  # a member with no dependency list at all: nothing to add to
        if MEMBER not in deps:
            lock = set_dep_lines(lock, member, deps + [MEMBER])
            notes.append(f"Cargo.lock: {member} depends on {MEMBER}")
    return lock, notes


def problems(lock: str, root: Path) -> list[str]:
    """What `fix` would still have to add: an empty list when the lockfile is complete."""
    out: list[str] = []
    if package_block(lock, MEMBER) is None:
        out.append(f"Cargo.lock has no {MEMBER} (a --locked build would refuse it)")
    else:
        version = workspace_version(root)
        span = package_block(lock, MEMBER)
        block = lock[span[0] : span[1]]
        if f'version = "{version}"' not in block:
            out.append(f"Cargo.lock: {MEMBER} is not at {version}")
        for dep in member_deps(root):
            if dep not in dep_lines(lock, MEMBER):
                out.append(f"Cargo.lock: {MEMBER} has no dependency {dep}")
    for member in members_depending_on_it(root):
        if MEMBER not in dep_lines(lock, member):
            out.append(f"Cargo.lock: {member} does not list {MEMBER}")
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report what is missing instead of writing")
    parser.add_argument("--files", action="store_true", help="print the paths a sync resets")
    args = parser.parse_args()

    if args.files:
        print("Cargo.lock")
        return 0

    target = root / "Cargo.lock"
    lock = target.read_text(encoding="utf-8")
    if args.check:
        found = problems(lock, root)
        for line in found:
            print(f"error: {line}", file=sys.stderr)
        if found:
            return 1
        print("ok: Cargo.lock knows this fork's Hebrew proofer")
        return 0

    fixed, notes = fix(lock, root)
    if fixed != lock:
        target.write_text(fixed, encoding="utf-8", newline="\n")
        for note in notes:
            print(note)
    found = problems(fixed, root)
    for line in found:
        print(f"error: {line}", file=sys.stderr)
    if found:
        return 1
    print("ok: nothing to do, Cargo.lock already knows the Hebrew proofer" if fixed == lock else f"ok: {len(notes)} change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
