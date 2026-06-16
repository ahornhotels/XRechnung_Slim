# Release-Checkliste — XRechnung_Slim

Schrittfolge, um eine neue Version zu veröffentlichen. `X.Y.Z` jeweils ersetzen
(z. B. `1.10.0`). Tag = `vX.Y.Z`.

## 1. Vorbereiten
- [ ] Änderungen committet, Arbeitsbaum sauber (`git status`).
- [ ] Tests grün: `python -m pytest tests_slim/` (erwartet: passed, 1 skipped = Live-DB).
- [ ] `VERSION` auf die neue Version gesetzt und committet
      (`chore: VERSION a.b.c -> X.Y.Z`).
- [ ] Kurze Release-Notes notiert (Was ist neu/behoben?) — erscheinen im UI des
      Auto-Updaters.

## 2. Taggen
- [ ] `git tag -a vX.Y.Z -m "Release X.Y.Z"`
- [ ] Tag zeigt auf den finalen Commit (`git show -s vX.Y.Z`).

## 3. Pushen
- [ ] `git push origin master`
- [ ] `git push origin vX.Y.Z`

## 4. GitHub-Release
- [ ] Auf GitHub aus dem Tag `vX.Y.Z` ein **Release** erstellen, Release-Notes
      eintragen. Kein Asset nötig — der Online-Installer zieht den Quellcode
      des Tags direkt.

## 5. Verifizieren
- [ ] Release-Seite zeigt Tag `vX.Y.Z`.
- [ ] Auf einer Test-/Hotel-Instanz im UI **„Update prüfen"** → bietet `X.Y.Z` an.
- [ ] **„Update anwenden"** → nur geänderte Dateien werden geladen, Dienst startet
      neu, `VERSION` zeigt danach `X.Y.Z`. Config/Daten unverändert.

## 6. Erstinstallation prüfen (nur bei Bedarf / größeren Releases)
- [ ] Auf einer frischen Maschine den Online-Einzeiler laufen lassen
      (siehe `INSTALL_FROM_GITHUB.md`) und einmal komplett durch den Wizard.

---

## Hinweise
- **Baseline-Tags lückenlos halten:** Der inkrementelle Updater difft
  `v<installiert>...v<neu>`. Jede ausgelieferte Version sollte einen Tag haben,
  sonst greift einmalig der volle Tree-Fallback (funktioniert, lädt nur mehr).
- **Versionsvergleich** ist rein numerisch (`1.10.0 > 1.9.0`). Tags konsequent
  `vMAJOR.MINOR.PATCH`.
- **Nie committen:** echte Configs/Secrets (`slim/config/*.json`, `*.key`) und
  Binärbundle (`install/python|jre|instantclient|wheels|nssm.exe`,
  KoSIT-Jar) — die `.gitignore` schützt davor.
- **Erstmigration der Alt-Hotels:** Instanzen, die noch die alte Slim aus
  `Suite8XRechnung` (ZIP-Updater) laufen haben, müssen **einmalig manuell** auf
  dieses Repo umgestellt werden; danach greift der inkrementelle Updater.
