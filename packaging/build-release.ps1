<#
  Builds the release files by hand, the same way the Release workflow does, with your Android signing key:

      .\packaging\build-release.ps1 -Keystore C:\path\release.keystore -PasswordFile C:\path\password.txt

  Writes release\SamanthaScreenMirror-windows.zip, its .sha256, SamanthaPhone.apk and SamanthaSetup.apk. Upload them to the
  GitHub release (for example: gh release create v0.5.0 release\* --notes-file notes.md).
  Needs the project's .venv with PyInstaller, a JDK 17+ and the Android SDK. The key never leaves this PC.
#>
param(
  [Parameter(Mandatory = $true)][string]$Keystore,
  [Parameter(Mandatory = $true)][string]$PasswordFile,
  [string]$Alias = "samantha"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$out = Join-Path $root "release"
$work = Join-Path ([IO.Path]::GetTempPath()) "samantha-release"

$env:SM_KEYSTORE = (Resolve-Path $Keystore).Path
$env:SM_KEYSTORE_PASS = (Get-Content -Raw $PasswordFile).Trim()
$env:SM_KEY_ALIAS = $Alias
try {
  & $python android/build.py
  if ($LASTEXITCODE -ne 0) { throw "the Android app did not build" }
} finally {
  Remove-Item Env:SM_KEYSTORE_PASS -ErrorAction SilentlyContinue
}

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
& $python -m PyInstaller packaging/samantha.spec --noconfirm --distpath "$work\dist" --workpath "$work\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory $out | Out-Null
Copy-Item packaging/README-FIRST.txt "$work\dist\SamanthaScreenMirror\"
Copy-Item samantha_mirror/phone_app/SamanthaPhone.apk "$out\SamanthaPhone.apk"
Copy-Item samantha_mirror/phone_app/SamanthaSetup.apk "$out\SamanthaSetup.apk"
Compress-Archive -Path "$work\dist\SamanthaScreenMirror" -DestinationPath "$out\SamanthaScreenMirror-windows.zip"
$hash = (Get-FileHash "$out\SamanthaScreenMirror-windows.zip" -Algorithm SHA256).Hash.ToLower()
"$hash  SamanthaScreenMirror-windows.zip" | Set-Content -Encoding ascii "$out\SamanthaScreenMirror-windows.zip.sha256"
Remove-Item -Recurse -Force $work
Get-ChildItem $out | Format-Table Name, Length
