<#
  Builds the release files by hand, the same way the Release workflow does, with your Android signing key:

      .\packaging\build-release.ps1 -Keystore C:\path\release.keystore -PasswordFile C:\path\password.txt

  Writes into release\:
    Mirra-for-Windows-Setup.exe       the Windows installer (what most people download)
    Mirra-for-Windows.zip (+ .sha256) the same program as a zip; the updater installs from this
    Mirra-for-Android-Setup.apk       for Android phones: installs the Mirra app
  Upload them to the GitHub release (for example: gh release create v0.6.0 release\* --notes-file notes.md).
  Needs the project's .venv with PyInstaller, a JDK 17+, the Android SDK and Inno Setup 6. The key never leaves this PC.
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
$work = Join-Path ([IO.Path]::GetTempPath()) "mirra-release"
$version = (& $python -c "import samantha_mirror; print(samantha_mirror.__version__)").Trim()
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 is not installed (winget install JRSoftware.InnoSetup)" }

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
$dist = "$work\dist\Mirra"
Copy-Item packaging/README-FIRST.txt "$dist\"

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory $out | Out-Null
Copy-Item samantha_mirror/phone_app/SamanthaSetup.apk "$out\Mirra-for-Android-Setup.apk"

function Zip-With-Sum($folder, $name) {
  Compress-Archive -Path $folder -DestinationPath "$out\$name"
  $hash = (Get-FileHash "$out\$name" -Algorithm SHA256).Hash.ToLower()
  "$hash  $name" | Set-Content -Encoding ascii "$out\$name.sha256"
}
Zip-With-Sum $dist "Mirra-for-Windows.zip"

& $iscc "/DVersion=$version" "/DDist=$dist" "/DOut=$out" "packaging\mirra.iss" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Remove-Item -Recurse -Force $work
Get-ChildItem $out | ForEach-Object { "{0,-45} {1,12:N0} bytes" -f $_.Name, $_.Length }
