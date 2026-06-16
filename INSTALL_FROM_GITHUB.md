# Installation aus GitHub

Zwei Wege. **Online-Installer** (empfohlen, kleiner Download) oder
**Voll-Bundle-ZIP** (offline/deterministisch).

Voraussetzungen in beiden Fällen: Windows Server, Administrator-Rechte und ein
auf dem Suite8-Server **bereits vorhandener Oracle-Client** (wird genutzt, nicht
mitgeliefert). Der Online-Installer braucht zusätzlich Internetzugang.

---

## Weg A — Online-Installer (empfohlen)

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

## Weg B — Voll-Bundle-ZIP (offline)

1. Auf `github.com/ahornhotels/XRechnung_Slim` → **Releases** → Asset
   `XRechnung_Slim-<version>.zip` herunterladen.
2. Nach z. B. `C:\FIDELIO\XRechnung_Slim` entpacken (enthält bereits Python,
   JRE, KoSIT — komplett).

> Hinweis: `git clone` allein genügt **nicht** — die Binärbausteine sind
> git-ignoriert und nur im Online-Installer bzw. im Release-ZIP enthalten.

---

## Gemeinsamer Abschluss (beide Wege)

1. `slim\setup_slim.cmd` **als Administrator** starten.
2. Wizard im Browser auf `http://127.0.0.1:8022/`:
   - Oracle-Verbindung (TNS/User/Passwort — wird verschlüsselt gespeichert).
   - Hoteldaten + Rechnungsnummer-Pattern.
   - Wizard zeigt das **Trigger-SQL** → der **DBA** führt es einmalig in
     Oracle (V8LIVE) aus.
3. Der Dienst `Suite8XRechnungSlim` wird installiert (Autostart, Port 8022).

## Updates

Später im UI **„Update prüfen / anwenden"** → der inkrementelle Updater holt
aus `ahornhotels/XRechnung_Slim` nur die geänderten Dateien. Konfiguration und
Daten bleiben erhalten.

---

## Für Maintainer: Repo installierbar machen (einmalig pro Release)

```powershell
# 1) Code + Tag pushen
git push origin master ; git push origin v1.9.0
# 2a) Online-Weg: nichts weiter nötig (Installer zieht den Source-Tag direkt)
# 2b) Offline-Weg: Bundle bauen + als Release-Asset veröffentlichen
powershell -ExecutionPolicy Bypass -File build_release.ps1 -Publish
```
