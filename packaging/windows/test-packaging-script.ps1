<# Check the real packaging script without compiling, signing or installing: one MSI, policy-checked before it is signed, and the Setup.exe built around it. #>
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$script = Join-Path $PSScriptRoot 'package.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($script, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'The packaging script does not parse.' }
if ($ast.Extent.Text -match 'windows-user|UserMsi') {
  throw 'WordCraft ships one dual-scope MSI; there is no separate per-user installer to package.'
}
$commands = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true))
$checks = @($commands | Where-Object {
  $_.InvocationOperator.ToString() -eq 'Ampersand' -and
    @($_.CommandElements | Where-Object { $_.Extent.Text -match 'check-install-policy.ps1' }).Count -gt 0
})
if ($checks.Count -ne 1) { throw 'Expected exactly one policy check in the packaging script.' }
$elements = $checks[0].CommandElements
$index = 0
while ($index -lt $elements.Count -and $elements[$index].Extent.Text -ne '-MsiPath') { $index++ }
if ($index + 1 -ge $elements.Count -or $elements[$index + 1].Extent.Text -ne '$Msi') {
  throw 'The policy check must inspect the MSI being packaged ($Msi).'
}
$signs = @($commands | Where-Object {
  $_.InvocationOperator.ToString() -eq 'Ampersand' -and
    @($_.CommandElements | Where-Object { $_.Extent.Text -match 'sign.ps1' }).Count -gt 0 -and
    $_.CommandElements[-1].Extent.Text -eq '$Msi'
})
if ($signs.Count -ne 1) { throw 'Expected the MSI to be signed exactly once.' }
if ($checks[0].Extent.StartOffset -ge $signs[0].Extent.StartOffset) { throw 'The MSI must pass the policy check before it is signed.' }
# The portable zip is the no-install build: without `portable.txt` beside the exe the app writes its
# profile to %APPDATA%\WordCraft, which is a copy that leaves traces (crates/control-key).
$text = $ast.Extent.Text
$marker = $text.IndexOf("Join-Path `$Portable 'portable.txt'")
if ($marker -lt 0) { throw 'The portable zip must carry portable.txt: the marker that keeps the profile beside the app.' }
if ($marker -gt $text.IndexOf('Compress-Archive')) { throw 'portable.txt must be written before the portable zip is compressed.' }
# The .exe is the installer people download: it must be built from the MSI that passed the policy
# check (not from a stale one), and signed by the same path as the MSI.
$bundle = @($commands | Where-Object {
  $_.InvocationOperator.ToString() -eq 'Ampersand' -and
    @($_.CommandElements | Where-Object { $_.Extent.Text -match 'wix build' }).Count -gt 0 -and
    @($_.CommandElements | Where-Object { $_.Extent.Text -match 'wordcraft-bundle.wxs' }).Count -gt 0
})
if ($bundle.Count -ne 1) { throw 'Expected the Setup.exe bundle to be built exactly once.' }
if ($bundle[0].Extent.StartOffset -lt $checks[0].Extent.StartOffset) { throw 'The Setup.exe must be built from the MSI after it passed the policy check.' }
$setupSigns = @($commands | Where-Object {
  $_.InvocationOperator.ToString() -eq 'Ampersand' -and
    @($_.CommandElements | Where-Object { $_.Extent.Text -match 'sign.ps1' }).Count -gt 0 -and
    $_.CommandElements[-1].Extent.Text -eq '$Setup'
})
if ($setupSigns.Count -ne 1) { throw 'Expected the Setup.exe to be signed exactly once.' }
if ($text.IndexOf('Compress-Archive') -lt $bundle[0].Extent.StartOffset) { throw 'The portable zip is built before the installer; the Setup.exe comes first in the release.' }
Write-Output 'PASS the WordCraft MSI is policy-checked before it is signed, the Setup.exe is built from it, and the portable zip is portable.'

