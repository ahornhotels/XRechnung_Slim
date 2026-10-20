# NSSM (Non-Sucking Service Manager)

`nssm.exe` — Version **2.24**, Build **win64**, 331 KB.

Wird vom Installer nach `install\nssm.exe` kopiert und richtet den
Windows-Dienst `Suite8XRechnungSlim` ein.

## Warum liegt die Datei im Repo?

`nssm.cc` war in der Praxis mehrfach nicht erreichbar und hat Installationen
scheitern lassen. Da der Installer den Quellcode dieses Repos ohnehin lädt,
ist die Datei damit immer zur Hand — ein Download entfällt.

Der Download von `nssm.cc` bleibt als Rückfallebene im Installer, damit auch
ältere Refs ohne dieses Verzeichnis weiter funktionieren.

## Lizenz

NSSM ist **Public Domain**. Aus der offiziellen `README.txt` des Projekts:

> NSSM is public domain. You may unconditionally use it and/or its source code
> for any purpose.

Herkunft: https://nssm.cc/release/nssm-2.24.zip (Verzeichnis `win64/`).
