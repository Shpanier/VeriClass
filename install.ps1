# Install (or update) VeriClass on Windows and start it. In PowerShell:
#
#   irm https://raw.githubusercontent.com/Shpanier/VeriClass/main/install.ps1 | iex
#
# It puts VeriClass in your user folder, in "VeriClass" (set $env:VERICLASS_DIR for
# another folder). Run the same line again later to update: your settings (.env),
# your database (vericlass.db) and your exercises (data\) are kept.
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 downloads many times slower while it draws a progress bar.
$ProgressPreference = "SilentlyContinue"
$repo = if ($env:VERICLASS_REPO) { $env:VERICLASS_REPO } else { "https://github.com/Shpanier/VeriClass" }
$branch = if ($env:VERICLASS_BRANCH) { $env:VERICLASS_BRANCH } else { "main" }
$dir = if ($env:VERICLASS_DIR) { $env:VERICLASS_DIR } else { Join-Path $HOME "VeriClass" }

if ((Test-Path (Join-Path $dir ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "==> Updating VeriClass in $dir"
    git -C $dir pull --ff-only
} else {
    Write-Host "==> Downloading VeriClass to $dir"
    $zip = Join-Path $env:TEMP "vericlass-$branch.zip"
    $tmp = Join-Path $env:TEMP "vericlass-unpack"
    Invoke-WebRequest "$repo/archive/refs/heads/$branch.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # Only the files of the release are written: .env, vericlass.db and data\ stay.
    Copy-Item -Path (Join-Path (Get-ChildItem $tmp | Select-Object -First 1).FullName "*") -Destination $dir -Recurse -Force
    Remove-Item $zip, $tmp -Recurse -Force
}
Write-Host "==> Starting. Next time: double-click start.bat in $dir"
& (Join-Path $dir "start.bat") @args
