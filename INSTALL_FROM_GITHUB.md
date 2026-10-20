# Installation aus GitHub

Voraussetzungen: Windows Server, Administrator-Rechte und Internetzugang
(zusätzlich zu GitHub & Co. auch `download.oracle.com`).

> **Oracle-Client, 64-bit:** Die App läuft mit 64-bit-Python und braucht eine
> **64-bit**-Oracle-Bibliothek. Der Client des Suite8-Servers ist häufig 32-bit
> und damit unbrauchbar. Der Installer prüft das (PE-Header) und lädt bei
> Bedarf den **Oracle Instant Client Basic Lite (x64)** nach
> `install\instantclient\`. Abschaltbar mit `-SkipOracle`.
>
> Fehlt die 64-bit-Bibliothek, fällt die App auf den oracledb-Thin-Mode
> zurück und bricht bei Datenbanken mit älterem Passwort-Verifier ab:
> `DPY-3015: password verifier type 0x939 is not supported ... in thin mode`.
>
> Instant Client 19 setzt die **Visual C++ Redistributable x64** voraus (die aus
> Visual Studio 2017). Auf Suite8-Servern meist vorhanden.

## 1. Online-Installer ausführen

Lädt Quellcode, portables Python, Temurin JRE, den KoSIT-Validator und — falls
kein 64-bit-Oracle-Client vorhanden ist — den Oracle Instant Client selbst aus
dem Netz. Jeder Download wird bis zu dreimal versucht. NSSM liegt dem Repo bei
(`vendor/nssm/`, Public Domain) und braucht keinen Download — `nssm.cc` war in
der Praxis mehrfach nicht erreichbar. **Ein** PowerShell-Befehl (als Administrator):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/ahornhotels/XRechnung_Slim/master/install_online.ps1 -OutFile $env:TEMP\install_online.ps1; & $env:TEMP\install_online.ps1"
```

Optionen:
```powershell
# anderes Zielverzeichnis / bestimmte Version / ohne KoSIT
.\install_online.ps1 -InstallDir "D:\Apps\XRechnung_Slim" -Ref v1.9.0 -SkipKosit

# ohne Instant-Client-Download (z.B. abgeschotteter Server oder eigener x64-Client)
.\install_online.ps1 -SkipOracle

# andere Instant-Client-Version
.\install_online.ps1 -InstantClientVersion "19.28.0.0.0"
```

Der Installer richtet alles unter dem Zielordner ein (Default
`C:\FIDELIO\XRechnung_Slim`). Beim Oracle-Client prüft er die Architektur
und meldet einen 32-bit-Fund ausdrücklich als unbrauchbar.

> `git clone` allein genügt **nicht** — die Binärbausteine (Python, JRE,
> KoSIT-Jar, Instant Client) sind git-ignoriert und werden erst vom Installer
> beschafft. Ausnahme: `nssm.exe` liegt unter `vendor/nssm/` im Repo.

## 2. Einrichtung abschließen

1. `slim\setup_slim.cmd` **als Administrator** starten.
2. Wizard im Browser auf `http://127.0.0.1:8022/`:
   - Oracle-Verbindung (TNS/User/Passwort — wird verschlüsselt gespeichert).
   - Hoteldaten + Rechnungsnummer-Pattern.
   - Wizard zeigt das **Trigger-SQL** → der **DBA** führt es einmalig in
     Oracle (V8LIVE) aus.
3. Der Dienst `Suite8XRechnungSlim` wird installiert (Autostart, Port 8022).

## 3. Updates

Später im UI **„Update prüfen / anwenden"** → der inkrementelle Updater holt
aus `ahornhotels/XRechnung_Slim` nur die geänderten Dateien. Konfiguration und
Daten bleiben erhalten.

---

## Für Maintainer: neues Release veröffentlichen

```powershell
git push origin master ; git push origin vX.Y.Z
```
Dann auf GitHub aus dem Tag `vX.Y.Z` ein **Release** anlegen (Release-Notes
eintragen). Mehr dazu in [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md). Ein
Asset ist nicht nötig — der Online-Installer zieht den Quellcode direkt.
