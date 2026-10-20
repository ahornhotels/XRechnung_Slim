<#
================================================================
 install_online.ps1  -  Online-Bootstrap-Installer fuer XRechnung_Slim

 Laedt alle Bausteine selbst aus dem Netz und richtet die App ein - OHNE
 grosses Bundle-ZIP. Voraussetzung: Internetzugang (python.org, PyPI,
 Adoptium, GitHub, nssm.cc) und eine 64-bit-Oracle-Bibliothek. Die App
 laeuft mit 64-bit-Python; der Client des Suite8-Servers ist haeufig 32-bit
 und damit fuer sie unbrauchbar. In dem Fall einen Instant Client (x64) nach
 install\instantclient\ legen. Geladen wird er NICHT - Oracle erlaubt keine
 Weiterverteilung.

 Was passiert:
   1) Quellcode (Release-Source-ZIP von GitHub) -> InstallDir
   2) Portable Python (python.org embeddable) + pip + requirements.txt
   3) Temurin JRE (Adoptium) -> install\jre   (fuer KoSIT)
   4) NSSM -> install\nssm.exe                 (Dienst-Wrapper)
   5) KoSIT-Validator + XRechnung-Konfig -> validation\   (optional)
   6) Oracle: 64-bit-Client bzw. Instant Client pruefen (kein Download)
   7) Hinweis: slim\setup_slim.cmd als Admin starten

 Aufruf (als Administrator empfohlen):
   powershell -ExecutionPolicy Bypass -File install_online.ps1
   ... -InstallDir "D:\Apps\XRechnung_Slim" -Ref v1.9.0 -SkipKosit
================================================================
#>
[CmdletBinding()]
param(
  [string]$InstallDir   = "C:\FIDELIO\XRechnung_Slim",
  [string]$Repo         = "ahornhotels/XRechnung_Slim",
  [string]$Ref          = "",                 # leer = neuester Release-Tag
  [string]$PythonVersion= "3.12.10",
  [string]$JreFeature   = "17",
  # KoSIT (itplr-kosit) - feste, getestete Versionen, bei Bedarf ueberschreibbar:
  [string]$KositConfigTag   = "v2026-01-31",
  [string]$KositConfigAsset = "xrechnung-3.0.2-validator-configuration-2026-01-31.zip",
  [string]$ValidatorVersion = "1.6.2",
  [switch]$SkipKosit,
  [switch]$SkipJre
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tmp = Join-Path $env:TEMP ("xrslim_dl_" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Info($m){ Write-Host $m -ForegroundColor Cyan }
function Ok($m){ Write-Host "   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "   $m" -ForegroundColor Yellow }

function Get-File($url, $dest) {
  Info "Download: $url"
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

function Get-DllArchitecture($path) {
  # Liest die Machine-Angabe aus dem PE-Header einer DLL/EXE.
  # 0x8664 = x64, 0x14C = x86. Rueckgabe: "x64", "x86" oder "" (unlesbar).
  try {
    $fs = [IO.File]::OpenRead($path)
    try {
      $buf = New-Object byte[] 4096
      $read = $fs.Read($buf, 0, $buf.Length)
      if ($read -lt 64) { return "" }
      $peOff = [BitConverter]::ToInt32($buf, 60)
      if ($peOff -lt 0 -or ($peOff + 6) -ge $read) { return "" }
      if ($buf[$peOff] -ne 0x50 -or $buf[$peOff + 1] -ne 0x45) { return "" }
      $machine = [BitConverter]::ToUInt16($buf, $peOff + 4)
      if ($machine -eq 0x8664) { return "x64" }
      if ($machine -eq 0x14C)  { return "x86" }
      return ""
    }
    finally { $fs.Close() }
  }
  catch { return "" }
}

try {
  Info "== XRechnung_Slim Online-Installer =="
  Info "   Ziel: $InstallDir"

  # ── 1) Quellcode ───────────────────────────────────────────────
  Info "[1/6] Quellcode laden..."
  $hdr = @{ "User-Agent" = "xrslim-installer" }
  $archiveUrls = @()
  if ($Ref) {
    # explizit angegeben: erst als Tag, dann als Branch versuchen
    $archiveUrls += "https://github.com/$Repo/archive/refs/tags/$Ref.zip"
    $archiveUrls += "https://github.com/$Repo/archive/refs/heads/$Ref.zip"
  } else {
    try {
      $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers $hdr
      $Ref = $rel.tag_name
      Ok "Neuestes Release: $Ref"
      $archiveUrls += "https://github.com/$Repo/archive/refs/tags/$Ref.zip"
    } catch {
      # Noch kein Release veroeffentlicht -> Default-Branch verwenden
      $info = Invoke-RestMethod "https://api.github.com/repos/$Repo" -Headers $hdr
      $Ref = $info.default_branch
      Warn "Kein Release gefunden - nutze Branch '$Ref'."
      $archiveUrls += "https://github.com/$Repo/archive/refs/heads/$Ref.zip"
    }
  }
  $srcZip = Join-Path $tmp "src.zip"
  $downloaded = $false
  foreach ($u in $archiveUrls) {
    try { Get-File $u $srcZip; $downloaded = $true; break }
    catch { Warn "nicht verfuegbar: $u" }
  }
  if (-not $downloaded) { throw "Quellcode-Download fehlgeschlagen fuer Ref '$Ref'." }
  $srcEx = Join-Path $tmp "src"
  Expand-Archive -Path $srcZip -DestinationPath $srcEx -Force
  $srcRoot = (Get-ChildItem $srcEx -Directory | Select-Object -First 1).FullName
  New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
  # Quellcode kopieren OHNE bestehende Configs/Daten zu ueberschreiben
  robocopy $srcRoot $InstallDir /E /XO /XD ".git" `
    (Join-Path $InstallDir "slim\config") (Join-Path $InstallDir "slim\data") (Join-Path $InstallDir "slim\logs") /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy (Quellcode) fehlgeschlagen ($LASTEXITCODE)" }
  Ok "Quellcode in $InstallDir"

  $installSub = Join-Path $InstallDir "install"
  New-Item -ItemType Directory -Force -Path $installSub | Out-Null

  # ── 2) Python embeddable + pip + requirements ─────────────────
  Info "[2/6] Python $PythonVersion + Pakete..."
  $pyDir = Join-Path $installSub "python"
  if (Test-Path (Join-Path $pyDir "python.exe")) {
    Ok "Python bereits vorhanden - uebersprungen"
  } else {
    $pyZip = Join-Path $tmp "py.zip"
    Get-File "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $pyZip
    Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force
    # site aktivieren, damit pip/Pakete gefunden werden
    Get-ChildItem $pyDir -Filter "python*._pth" | ForEach-Object {
      (Get-Content $_.FullName) -replace '^\s*#\s*import site', 'import site' | Set-Content $_.FullName
    }
    $getpip = Join-Path $tmp "get-pip.py"
    Get-File "https://bootstrap.pypa.io/get-pip.py" $getpip
    & (Join-Path $pyDir "python.exe") $getpip --no-warn-script-location
    Ok "Python + pip installiert"
  }
  Info "   pip install -r requirements.txt ..."
  & (Join-Path $pyDir "python.exe") -m pip install --no-warn-script-location -r (Join-Path $InstallDir "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen" }
  Ok "Python-Pakete installiert"

  # ── 3) Temurin JRE ────────────────────────────────────────────
  if ($SkipJre) { Warn "[3/6] JRE uebersprungen (-SkipJre)" }
  else {
    Info "[3/6] Temurin JRE $JreFeature..."
    $jreDir = Join-Path $installSub "jre"
    if (Test-Path (Join-Path $jreDir "bin\java.exe")) { Ok "JRE bereits vorhanden" }
    else {
      $jreZip = Join-Path $tmp "jre.zip"
      Get-File "https://api.adoptium.net/v3/binary/latest/$JreFeature/ga/windows/x64/jre/hotspot/normal/eclipse?project=jdk" $jreZip
      $jreEx = Join-Path $tmp "jre"
      Expand-Archive -Path $jreZip -DestinationPath $jreEx -Force
      $inner = (Get-ChildItem $jreEx -Directory | Select-Object -First 1).FullName
      if (Test-Path $jreDir) { Remove-Item $jreDir -Recurse -Force }
      Move-Item $inner $jreDir
      Ok "JRE in install\jre"
    }
  }

  # ── 4) NSSM ───────────────────────────────────────────────────
  Info "[4/6] NSSM..."
  $nssm = Join-Path $installSub "nssm.exe"
  if (Test-Path $nssm) { Ok "NSSM bereits vorhanden" }
  else {
    $nssmZip = Join-Path $tmp "nssm.zip"
    Get-File "https://nssm.cc/release/nssm-2.24.zip" $nssmZip
    $nssmEx = Join-Path $tmp "nssm"
    Expand-Archive -Path $nssmZip -DestinationPath $nssmEx -Force
    Copy-Item (Join-Path $nssmEx "nssm-2.24\win64\nssm.exe") $nssm -Force
    Ok "nssm.exe in install\"
  }

  # ── 5) KoSIT-Validator + XRechnung-Konfig ─────────────────────
  if ($SkipKosit) { Warn "[5/6] KoSIT uebersprungen (-SkipKosit) - kosit_validation in app_settings auf false setzen" }
  else {
    Info "[5/6] KoSIT-Validator + Konfiguration ($KositConfigTag / validator $ValidatorVersion)..."
    $valDir = Get-ChildItem (Join-Path $InstallDir "validation") -Directory -Filter "xrechnung-*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $valDir) { throw "validation\xrechnung-* Ordner fehlt (kam mit dem Quellcode?)" }
    $valDir = $valDir.FullName
    # KoSIT-Konfig-Release (enthaelt scenarios + resources inkl. UBL-XSDs)
    $cfgZip = Join-Path $tmp "kositcfg.zip"
    Get-File "https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/$KositConfigTag/$KositConfigAsset" $cfgZip
    $cfgEx = Join-Path $tmp "kositcfg"
    Expand-Archive -Path $cfgZip -DestinationPath $cfgEx -Force
    # ZIP entpackt entweder flach oder in einen einzigen Unterordner
    $cfgRoot = $cfgEx
    if (((Get-ChildItem $cfgEx -Directory).Count -eq 1) -and ((Get-ChildItem $cfgEx -File).Count -eq 0)) {
      $cfgRoot = (Get-ChildItem $cfgEx -Directory | Select-Object -First 1).FullName
    }
    robocopy $cfgRoot $valDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
    # Validator-JAR (Standalone)
    $jar = Join-Path $valDir "kosit-validator.jar"
    Get-File "https://github.com/itplr-kosit/validator/releases/download/v$ValidatorVersion/validator-$ValidatorVersion-standalone.jar" $jar
    Ok "KoSIT-Material in $valDir"
  }

  # ── 6) Oracle-Client (nur erkennen) ───────────────────────────
  Info "[6/6] Oracle-Client pruefen (wird NICHT geladen)..."
  # Die App laeuft mit 64-bit-Python und kann nur eine 64-bit-oci.dll laden.
  # Ein 32-bit-Client - auf Suite8-Servern der Normalfall - ist fuer sie
  # unbrauchbar (DPI-1047 "not the correct architecture"). Fruehere Fassungen
  # nahmen den ersten Treffer OHNE Architektur-Pruefung und meldeten ihn als
  # "gefunden"; der Hinweis auf 'oracle_client_lib_dir' blieb dadurch aus und
  # die Installation lief spaeter im Thin-Mode in DPY-3015 (alter Verifier).
  # Darum: alle Treffer durchgehen und einen 64-bit-Client bevorzugen.
  $ora64 = $null
  $ora32 = $null
  foreach ($root in @("C:\ORACLE","C:\oracle","C:\app","C:\Program Files\Oracle")) {
    if (-not (Test-Path $root)) { continue }
    $hits = Get-ChildItem $root -Recurse -Filter "oci.dll" -ErrorAction SilentlyContinue
    foreach ($hit in $hits) {
      $arch = Get-DllArchitecture $hit.FullName
      if ($arch -eq "x64") { $ora64 = $hit; break }
      if ($arch -eq "x86" -and -not $ora32) { $ora32 = $hit }
    }
    if ($ora64) { break }
  }

  $bundled = Join-Path $InstallDir "install\instantclient\oci.dll"
  $bundledOk = $false
  if (Test-Path $bundled) {
    if ((Get-DllArchitecture $bundled) -eq "x64") { $bundledOk = $true }
  }

  if ($ora64) {
    Ok "Oracle-Client (64-bit) gefunden: $($ora64.Directory.FullName)"
  }
  elseif ($bundledOk) {
    Ok "Mitgelieferter 64-bit Instant Client vorhanden: $(Split-Path $bundled -Parent)"
  }
  else {
    if ($ora32) {
      Warn "Oracle-Client gefunden, aber 32-bit: $($ora32.Directory.FullName)"
      Warn "Die App laeuft mit 64-bit-Python und kann diesen Client NICHT laden."
    }
    else {
      Warn "Kein Oracle-Client gefunden."
    }
    Warn "Ohne 64-bit-Client nutzt die App den oracledb-Thin-Mode. Verlangt die"
    Warn "Suite8-DB den Thick-Mode (Fehler DPY-3015, alter Password-Verifier),"
    Warn "dann einen 64-bit Instant Client Basic Lite (x64) nach"
    Warn "'install\instantclient\' legen ODER im Wizard 'oracle_client_lib_dir'"
    Warn "auf das bin-Verzeichnis eines 64-bit-Clients setzen."
  }

  Write-Host ""
  Info "== Installation vorbereitet =="
  Write-Host "  Naechster Schritt: als Administrator ausfuehren:" -ForegroundColor Yellow
  Write-Host "     `"$InstallDir\slim\setup_slim.cmd`""
  Write-Host "  Danach oeffnet sich der Wizard auf http://127.0.0.1:8022/"
}
finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
