# Installation aus GitHub

Voraussetzungen: Windows Server, Administrator-Rechte, Internetzugang und ein
auf dem Suite8-Server **bereits vorhandener Oracle-Client** (wird genutzt, nicht
mitgeliefert).

## 1. Online-Installer ausführen

Lädt Quellcode, portables Python, Temurin JRE, NSSM und den KoSIT-Validator
selbst aus dem Netz. **Ein** PowerShell-Befehl (als Administrator):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/ahornhotels/XRechnung_Slim/master/install_online.ps1 -OutFile $env:TEMP\install_online.ps1; & $env:TEMP\install_online.ps1"
```

Optionen:
```powershell
# anderes Zielverzeichnis / bestimmte Version / ohne KoSIT
.\install_online.ps1 -InstallDir "D:\Apps\XRechnung_Slim" -Ref v1.9.0 -SkipKosit
```

Der Installer richtet alles unter dem Zielordner ein (Default
`C:\FIDELIO\XRechnung_Slim`) und erkennt den vorhandenen Oracle-Client.

> `git clone` allein genügt **nicht** — die Binärbausteine (Python, JRE, NSSM,
> KoSIT-Jar) sind git-ignoriert und werden erst vom Installer nachgeladen.

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
