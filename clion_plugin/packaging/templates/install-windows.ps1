# OS Lab — exam client installer (Windows).
# Run via install-windows.bat (double-click). Installs the OS Lab plugin into
# CLion, points it at your instructor's backend, and launches CLion. No admin.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "=============================================="
Write-Host "  OS Lab - Exam Client Installer (Windows)"
Write-Host "=============================================="
Write-Host ""

function Read-Conf($path) {
  $h = @{}
  if (Test-Path $path) {
    foreach ($line in Get-Content $path) {
      if ($line -match '^\s*#') { continue }
      if ($line -match '^\s*([A-Za-z_]+)\s*=\s*(.*)$') {
        $h[$matches[1]] = $matches[2].Trim()
      }
    }
  }
  return $h
}

function Xml-Escape($s) {
  if ($null -eq $s) { return "" }
  return $s.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

$conf = Read-Conf (Join-Path $root "exam.conf")
$backend = $conf["BACKEND_URL"]; if (-not $backend) { $backend = "http://127.0.0.1:8000" }
$projectDir = $conf["PROJECT_DIR"]
$devCode = $conf["DEV_LOGIN_CODE"]
$zip = Join-Path $root "plugin\oslab-exam-plugin.zip"

Write-Host "Backend:  $backend"
if ($projectDir) { Write-Host "Project:  $projectDir" }
Write-Host ""

if (-not (Test-Path $zip)) {
  Write-Host "X Missing $zip - is this the full package folder?" -ForegroundColor Red
  Read-Host "Press Enter to close"; exit 1
}

# --- locate the newest CLion config directory --------------------------------
$jb = Join-Path $env:APPDATA "JetBrains"
$configs = @(Get-ChildItem -Path $jb -Directory -Filter "CLion*" -ErrorAction SilentlyContinue | Sort-Object Name)
if ($configs.Count -eq 0) {
  Write-Host "X Couldn't find a CLion config folder." -ForegroundColor Red
  Write-Host "  Install CLion and launch it once, then run this installer again."
  Read-Host "Press Enter to close"; exit 1
}
$config = $configs[-1].FullName
Write-Host "CLion config: $config"

# --- close CLion so it reloads the plugin on next launch ---------------------
$procs = Get-Process clion64, clion -ErrorAction SilentlyContinue
foreach ($p in $procs) { $p.CloseMainWindow() | Out-Null }
Start-Sleep -Seconds 2
Get-Process clion64, clion -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# --- install the plugin (extract into the plugins dir) -----------------------
$plugins = Join-Path $config "plugins"
New-Item -ItemType Directory -Force -Path $plugins | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
$top = ($archive.Entries[0].FullName -split '/')[0]
$archive.Dispose()
if ($top) {
  $target = Join-Path $plugins $top
  if (Test-Path $target) { Remove-Item -Recurse -Force $target }
}
Expand-Archive -Path $zip -DestinationPath $plugins -Force
Write-Host "OK Plugin installed." -ForegroundColor Green

# --- preset the backend URL (application-level plugin settings) --------------
$options = Join-Path $config "options"
New-Item -ItemType Directory -Force -Path $options | Out-Null
$xml = @"
<application>
  <component name="OsLabSettings">
    <option name="backendUrl" value="$(Xml-Escape $backend)" />
    <option name="devLoginCode" value="$(Xml-Escape $devCode)" />
  </component>
</application>
"@
Set-Content -Path (Join-Path $options "oslab.xml") -Value $xml -Encoding UTF8
Write-Host "OK Backend URL configured." -ForegroundColor Green

# --- find and launch CLion ---------------------------------------------------
$exe = $null
$cmd = Get-Command clion64.exe -ErrorAction SilentlyContinue
if ($cmd) { $exe = $cmd.Source }
if (-not $exe) {
  $roots = @(
    (Join-Path $env:LOCALAPPDATA 'JetBrains\Toolbox\apps'),
    (Join-Path $env:ProgramFiles 'JetBrains')
  )
  if (${env:ProgramFiles(x86)}) { $roots += (Join-Path ${env:ProgramFiles(x86)} 'JetBrains') }
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $f = Get-ChildItem -Path $r -Recurse -Filter clion64.exe -ErrorAction SilentlyContinue |
           Sort-Object FullName | Select-Object -Last 1
      if ($f) { $exe = $f.FullName; break }
    }
  }
}

Write-Host ""
if ($exe) {
  Write-Host "Launching CLion..."
  if ($projectDir) { Start-Process $exe -ArgumentList "`"$projectDir`"" } else { Start-Process $exe }
} else {
  Write-Host "Plugin installed, but CLion was not found. Please open CLion yourself." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  - Open the 'OS Lab' tool window on the right (it should appear automatically)."
Write-Host "  - Log in with the code your instructor gave you."
Write-Host "  - The exam runs in full screen. Leaving CLion notifies your instructor."
Read-Host "Press Enter to close"
