# Windows installation policy checks

## What ships

| File | What it is |
| --- | --- |
| `wordcraft-<version>-windows-<arch>-Setup.exe` | **The installer.** A WiX bundle (`wordcraft-bundle.wxs`) with the MSI inside it: double-click, installs for the current account with no administrator rights, licence → progress → "Launch WordCraft". Unsigned unless signing secrets are configured. |
| `wordcraft-<version>-windows-<arch>.msi` | The package the `.exe` wraps, shipped beside it for `msiexec` deployments and for installing for every user (`ALLUSERS=1`). It is the record of what is installed — files, shortcuts, associations, scope rules below. |
| `wordcraft-<version>-windows-<arch>-portable.zip` | No installation: unpack, run, everything stays in `WordCraft-data` beside the exe. |

The `.exe` carries its MSI compressed, so installing needs no network and no second file. It is
built from the MSI *after* that MSI passed the policy check and was signed, and is itself signed by
the same `sign.ps1` path; `test-packaging-script.ps1` holds both properties.

The `.exe` is the only one of the three that can be missing: `package.ps1` builds it inside a `try`,
so a WiX bundle failure leaves the MSI and the portable zip to be published and prints a warning
instead of ending the run. A release without it installs with the MSI (double-click for the current
account, `msiexec /i … ALLUSERS=1` for everyone); the release notes name the download that exists.

New installations default to the current account under `Programs\ArtCraft\<App>`.
The first setup page offers installation for everyone. Scope is selected before duplicate
checks and directory costing. An update uses the existing context's remembered exact folder;
`INSTALLFOLDER` supplied explicitly is never replaced. It is a secure MSI property so the
chosen folder reaches the elevated installer. Silent machine updates pass `ALLUSERS=1`.
A cross-context copy is refused; changing context means uninstalling the old copy first.

App registration follows the selected context. Existing optional shortcuts and file-handler
choices stay app-owned. No new cleanup operation or model/settings migration is introduced.
Packaged resources remain package-owned; separately downloaded shared models are not caches
and are outside this installer's ownership.

## Repeatable metadata tests

On Windows with WiX 5.0.2 and its matching UI/Util extensions:

```powershell
./packaging/windows/test-install-policy.ps1 -OutputDirectory ./target/install-policy-tests
```

The script builds x64, x86 and arm64 packages with deliberately non-executable payloads. It
uses the actual package source and compiled database. A safe Windows Installer session checks
24 scope/registration/maintenance cases, remembered and explicit custom folders, sequencing,
upgrade identity and the original registration inventory recorded in `install-policy.json`.
The release packaging script runs the compiled checker before signing. Packaging CI runs the
small fixture builds without compiling the Rust application.

Never install or distribute the `NOT-INSTALLABLE.msi` fixtures as an app. Passing these checks
does not prove real installation, elevation, legacy-version upgrades, registry writes, optional
shortcut/menu behaviour, cancellation, rollback or uninstall. Those still require the real
payload in an authorised clean Windows test environment. Cross-architecture metadata is not
execution evidence on those architectures. Existing open installer/association PRs must be
reconciled before publication. Nothing here changes macOS/Linux native packaging conventions.
