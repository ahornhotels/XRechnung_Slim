<#
================================================================
 build_release.ps1
 Baut ein VOLL-BUNDLE-ZIP fuer die ERSTINSTALLATION von XRechnung_Slim.

 Inhalt (self-contained): Quellcode + portable Python + Temurin JRE +
 Oracle Instant Client + NSSM + pip-Wheels + KoSIT-Validierungsartefakte.

 NICHT enthalten: echte Configs/Secrets, Laufzeitdaten (slim/data, slim/logs),
 VCS-/Cache-Ordner (.git, __pycache__, .pytest_cache, .venv, dist).

 -> Das Ergebnis landet unter dist\XRechnung_Slim-<version>.zip und wird als
    Release-Asset hochgeladen (Erstinstallation). Laufende Updates laufen
    getrennt ueber den inkrementellen Updater (kein ZIP).

 Aufruf:
   powershell -ExecutionPolicy Bypass -File build_release.ps1
   powershell -ExecutionPolicy Bypass -File build_release.ps1 -Publish
   powershell -ExecutionPolicy Bypass -File build_release.ps1 -Publish -Notes "Release Notes ..."

 Voraussetzung: die git-ignorierten Binaerdateien muessen lokal vorhanden sein
 (install\python, install\jre, install\instantclient, install\nssm.exe,
 install\wheels) sowie das KoSIT-Jar unter validation\.
================================================================
#>
[CmdletBinding()]
param(
  [switch]$Publish,
  [string]$Notes = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$version = (Get-Content (Join-Path $root "VERSION") -Raw).Trim()
$tag     = "v$version"
$name    = "XRechnung_Slim-$version"
$dist    = Join-Path $root "dist"
$stage   = Join-Path $dist $name
$zip     = Join-Path $dist "$name.zip"

Write-Host "== Build $name ==" -ForegroundColor Cyan

# --- Vollstaendigkeits-Check der Binaerdateien (sonst waere das Bundle kaputt) ---
$required = @(
  "install\python\python.exe",
  "install\nssm.exe",
  "install\jre\bin\java.exe",
  "install\instantclient\oci.dll"
)
foreach ($r in $required) {
  if (-not (Test-Path (Join-Path $root $r))) {
    throw "Binaerdatei fehlt: $r - Bundle waere unvollstaendig. install\ befuellen."
  }
}
if (-not (Get-ChildItem (Join-Path $root "validation") -Recurse -Filter "kosit-validator.jar" -ErrorAction SilentlyContinue)) {
  Write-Warning "kosit-validator.jar nicht gefunden - KoSIT-Validierung wuerde im Bundle fehlen."
}

# --- Staging-Verzeichnis frisch aufsetzen ---
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# --- robocopy: alles spiegeln ausser Ausschluessen ---
# Per Name (an JEDER Stelle ausgeschlossen):
$xdNames = @("__pycache__", ".pytest_cache", ".venv", "node_modules", ".git")
# Per Pfad (nur exakt dieses Verzeichnis):
$xdPaths = @(
  (Join-Path $root "dist"),
  (Join-Path $root "slim\data"),
  (Join-Path $root "slim\logs")
)
# Dateien ausschliessen: Caches + ECHTE Configs/Secrets (.example bleibt drin)
$xf = @("*.pyc", "hotel.json", "connection.json", "connection.key",
        "app_settings.json", "update.json", "local_admin.json",
        ".setup_done", ".jwt_secret", ".token_cache.bin")

$rcArgs = @($root, $stage, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
foreach ($d in $xdNames) { $rcArgs += @("/XD", $d) }
foreach ($d in $xdPaths) { $rcArgs += @("/XD", $d) }
$rcArgs += "/XF"; $rcArgs += $xf

robocopy @rcArgs | Out-Null
# robocopy: Exit-Codes < 8 = Erfolg
if ($LASTEXITCODE -ge 8) { throw "robocopy fehlgeschlagen (Code $LASTEXITCODE)" }

# --- ZIP bauen ---
# WICHTIG: NICHT ZipFile.CreateFromDirectory verwenden - unter .NET Framework
# (Windows PowerShell 5.1) schreibt das BACKSLASHES als Pfadtrenner, was die
# ZIP-Spezifikation verletzt und beim Entpacken die Unterordner zerstoert.
# Daher Eintraege manuell mit '/'-Trennern anlegen.
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "Komprimiere -> $zip ..."
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stageFull = (Resolve-Path $stage).Path.TrimEnd('\')
$fs = [System.IO.File]::Open($zip, [System.IO.FileMode]::CreateNew)
try {
  $archive = New-Object System.IO.Compression.ZipArchive(
    $fs, [System.IO.Compression.ZipArchiveMode]::Create)
  try {
    Get-ChildItem -Path $stage -Recurse -File | ForEach-Object {
      $rel = $_.FullName.Substring($stageFull.Length + 1).Replace('\', '/')
      [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $archive, $_.FullName, $rel,
        [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
  } finally { $archive.Dispose() }
} finally { $fs.Dispose() }
Remove-Item $stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "FERTIG: $zip ($sizeMb MB)" -ForegroundColor Green

# --- Optional: GitHub-Release anlegen + Asset hochladen ---
if ($Publish) {
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "gh CLI nicht gefunden - Release manuell anlegen und ZIP als Asset hochladen."
  }
  if ([string]::IsNullOrWhiteSpace($Notes)) { $Notes = "Release $version" }
  Write-Host "== GitHub-Release $tag anlegen + Asset hochladen =="
  gh release create $tag $zip --title $version --notes $Notes
  Write-Host "Release $tag veroeffentlicht." -ForegroundColor Green
} else {
  Write-Host ""
  Write-Host "Naechster Schritt (manuell):" -ForegroundColor Yellow
  Write-Host "  1) git push origin master ; git push origin $tag"
  Write-Host "  2) gh release create $tag `"$zip`" --title $version --notes `"...`""
  Write-Host "     (oder im GitHub-Release das ZIP als Asset hochladen)"
}
