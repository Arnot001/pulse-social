param(
    [string]$PdhRepo = "",
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if (-not $PdhRepo) {
    $PdhRepo = Join-Path (Split-Path $RepoRoot -Parent) "pulse-data-hunter"
}
$PdhRepo = [System.IO.Path]::GetFullPath($PdhRepo)

$ReleaseRoot = Join-Path $RepoRoot "release"
$GeneratedRoot = Join-Path $ReleaseRoot "generated"
$OutputRoot = Join-Path $ReleaseRoot "output"
$AppOutput = Join-Path $OutputRoot "Pulse Social"
$AssetsPath = Join-Path $RepoRoot "assets"
$AssetsDataArg = "$AssetsPath;assets"

Write-Host ""
Write-Host "PULSE // SOCIAL BETA BUILD" -ForegroundColor Magenta
Write-Host "Repo: $RepoRoot"
Write-Host "PDH : $PdhRepo"
Write-Host ""

if (-not (Test-Path (Join-Path $PdhRepo "manifest.json"))) {
    throw "Pulse Data Hunter was not found at '$PdhRepo'. Pass -PdhRepo with the PDH repository path."
}

$pdhManifest = Get-Content (Join-Path $PdhRepo "manifest.json") -Raw | ConvertFrom-Json
if ($pdhManifest.version -ne "0.11.100") {
    throw "Release beta expects PDH 0.11.100 but found '$($pdhManifest.version)'."
}

if (-not $SkipTests) {
    Write-Host "[1/5] Focused release tests..." -ForegroundColor Cyan
    python -m pytest `
        tests/test_launcher_status.py `
        tests/test_browser_control.py `
        tests/test_tiktok_browser_session.py `
        tests/test_emoji_picker.py `
        tests/test_emoji_assets.py `
        tests/test_release_bootstrap.py `
        tests/test_pulse_splash.py `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw "Focused release tests failed."
    }
} else {
    Write-Host "[1/5] Tests skipped by request." -ForegroundColor Yellow
}

Write-Host "[2/5] Cleaning generated output..." -ForegroundColor Cyan
Remove-Item $GeneratedRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $GeneratedRoot -ItemType Directory -Force | Out-Null
New-Item (Join-Path $GeneratedRoot "spec") -ItemType Directory -Force | Out-Null
New-Item $OutputRoot -ItemType Directory -Force | Out-Null

Write-Host "[3/5] Building Pulse Social..." -ForegroundColor Cyan
$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "Pulse Social",
    "--distpath", $OutputRoot,
    "--workpath", (Join-Path $GeneratedRoot "build"),
    "--specpath", (Join-Path $GeneratedRoot "spec"),
    "--add-data", $AssetsDataArg,
    "--collect-submodules", "platforms",
    "--collect-submodules", "commerce",
    "--collect-submodules", "pulse_backend",
    "--collect-all", "playwright",
    "--hidden-import", "pulse_social_launcher",
    "--hidden-import", "pulse_social_ui",
    "--hidden-import", "x_auto_post_ui",
    "--hidden-import", "tiktok_shop_ui",
    "--hidden-import", "tiktok_auto_post_ui",
    "--hidden-import", "tiktok_cleanup_ui",
    "release_bootstrap.py"
)
python @pyiArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if (-not (Test-Path (Join-Path $AppOutput "Pulse Social.exe"))) {
    throw "Build completed without Pulse Social.exe."
}

Write-Host "[4/5] Bundling PDH 0.11.100..." -ForegroundColor Cyan
$PdhOutput = Join-Path $AppOutput "pdh_extension"
New-Item $PdhOutput -ItemType Directory -Force | Out-Null

foreach ($name in @("manifest.json", "background-entry.js", "background.js", "content.js")) {
    Copy-Item (Join-Path $PdhRepo $name) (Join-Path $PdhOutput $name) -Force
}
foreach ($folder in @("core", "packs", "ui")) {
    Copy-Item (Join-Path $PdhRepo $folder) (Join-Path $PdhOutput $folder) -Recurse -Force
}

$Licenses = Join-Path $AppOutput "licenses"
New-Item $Licenses -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RepoRoot "assets\emoji\ATTRIBUTION.md") (Join-Path $Licenses "TWEMOJI.md") -Force
Copy-Item (Join-Path $ReleaseRoot "BETA_README.txt") (Join-Path $AppOutput "BETA_README.txt") -Force

Write-Host "[5/5] Installer..." -ForegroundColor Cyan
if ($SkipInstaller) {
    Write-Host "Installer skipped. Portable beta folder is ready:" -ForegroundColor Yellow
    Write-Host "  $AppOutput"
    exit 0
}

$isccCandidates = @(
    (Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Inno Setup 6\ISCC.exe"),
    (Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $isccCandidates) {
    Write-Host "Inno Setup 6 was not found. Portable beta folder is ready:" -ForegroundColor Yellow
    Write-Host "  $AppOutput"
    Write-Host "Install Inno Setup 6 later, then run this script again to create the installer."
    exit 0
}

$Iscc = $isccCandidates[0]
& $Iscc (Join-Path $ReleaseRoot "PulseSocial.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}

Write-Host ""
Write-Host "BETA READY" -ForegroundColor Green
Write-Host "Portable: $AppOutput"
Write-Host "Installer: $(Join-Path $OutputRoot 'installer')"
