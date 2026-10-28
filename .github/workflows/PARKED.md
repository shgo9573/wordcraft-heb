# Workflows that are parked (off) in this fork

GitHub Actions runs a workflow file only when its name ends in **`.yml`** or **`.yaml`**. The files
here end in **`.yml.parked`**, so they do not run — that is the switch.

| File | What it did | Why it is off |
| --- | --- | --- |
| `ci.yml.parked` | `cargo xtask ci` on every push and PR, through `craft-common-actions` | it is the heaviest workflow in the repo (a full Linux build) and holds the minutes the Windows installer needs |
| `release.yml.parked` | the suite's multi-platform release (Linux, macOS, Windows), with Apple and Windows signing secrets | it needs certificates this fork does not have, and it builds Linux |
| `sonarcloud.yml.parked` | static analysis upload | minutes, and nothing in the Hebrew overlay depends on it |
| `nix.yml.parked`, `freebsd.yml.parked` | Nix and FreeBSD builds | other platforms |
| `printing.yml.parked` | the print-engine matrix (Linux/macOS/Windows) | unrelated to the Hebrew interface |
| `windows-arm64.yml.parked` | a nightly ARM64 MSI, installed and smoke-tested | an extra full Windows build every night; the x64 MSI is the one this fork ships |
| `linux-release.yml.ym` | the Hebrew Linux build (tar.gz + AppImage) and its release | parked so the daily run only spends minutes on Windows |

Still on:

* **`sync-upstream.yml`** — the daily upstream sync, the Windows x64 MSI + portable zip, and the
  release (`v<version>-he.win.1`).
* **`hebrew-check.yml`** — `cargo check`, the Hebrew proofing tests and the interface tests on a PR.
* **`packaging-lint.yml`** — actionlint, which checks the workflow files themselves (it caught a
  real shellcheck error in `sync-upstream.yml`).

## Turning one back on

```sh
git mv .github/workflows/ci.yml.parked .github/workflows/ci.yml
git commit -m "ci: turn the gate back on" && git push
```

Or from the GitHub web UI: Actions › the parked workflow is not listed (it cannot be), so edit the
file's name there (the pencil is disabled for renames — use the command line above). Do the same for
`linux-release.yml.ym` → `linux-release.yml` to build Linux packages again.

## Note on the parked `ci.yml`

`ci.yml` runs `cargo fmt --all -- --check`. This fork's own Rust (`crates/ui-egui/src/rtl.rs`,
`crates/proof/src/he/`) was written without a local toolchain, so before turning `ci.yml` back on run

```sh
cargo fmt --all
```

once and commit the result — the repository's `rustfmt.toml` (`max_width = 150`,
`use_small_heuristics = "Max"`) collapses short blocks onto one line, and rustfmt is the only thing
that decides where.
