# XRechnung Validation Artifacts

Diese Dateien werden zur XRechnung-Validierung verwendet. Sie sind im Git committed (klein genug) und werden auch im Inno-Installer gebuendelt.

## Vorhandene Dateien

| Datei / Verzeichnis | Quelle | Zweck |
|---|---|---|
| `kosit-validator.jar` | KoSIT Validator 1.6.2 (GitHub) | Standalone-JAR, ausgefuehrt via `java -jar` |
| `scenarios.xml` | KoSIT validator-configuration-xrechnung v2026-01-31 | Validator-Konfiguration fuer XRechnung 3.0.x |
| `resources/` | KoSIT Konfig | Schematron, XSL, XSD-Referenzen |
| `EN16931-*.xsl` | KoSIT Konfig | EU-Norm Validierungs-Transformations |
| `ubl-2.1/` | OASIS UBL 2.1 (separater Download) | Schema fuer lxml-Pre-Validierung (`xml_builder.validate_xsd`) |
| `README.md` | KoSIT | KoSIT-Original-README |
| `CHANGELOG.md` | KoSIT | KoSIT-Konfig-Changelog |

## Versionen aktuell

- KoSIT Validator: **1.6.2**
- KoSIT Konfiguration XRechnung: **v2026-01-31** (kompatibel mit XRechnung 3.0.x)
- OASIS UBL: **2.1**

## Voraussetzung auf dem Zielserver

**Java JRE >= 11** wird benoetigt um die JAR auszufuehren. Der Installer bringt eine portable Adoptium Temurin JRE in `install/jre/` mit; der `kosit_validator`-Wrapper sucht zuerst dort, dann im PATH.

## Update auf neue XRechnung-Version

1. Neues Unterverzeichnis `validation/xrechnung-X.Y.Z/`
2. Aktuelle KoSIT-Konfig hier auspacken
3. UBL-Schema kopieren (oder fortgesetzt das von KoSIT mitgelieferte unter `resources/ubl/` nutzen)
4. `app_settings.json: "xrechnung_version": "X.Y.Z"` umstellen
5. Bei breaking changes: `templates/xrechnung_X.Y.xml.j2` anpassen
6. Tests gegen KoSIT-Beispiele laufen lassen

## Manuelles Update-Skript (PowerShell)

```powershell
$ver = "3.0.3"  # neue Zielversion
$dest = "validation/xrechnung-$ver"
mkdir $dest -Force

# 1. KoSIT-JAR
$jar = (Invoke-RestMethod "https://api.github.com/repos/itplr-kosit/validator/releases/latest" -UserAgent "Mozilla").assets | ? name -match "validator.*standalone.*jar"
Invoke-WebRequest $jar.browser_download_url -OutFile "$dest\kosit-validator.jar" -UseBasicParsing

# 2. KoSIT-Konfig
$cfg = (Invoke-RestMethod "https://api.github.com/repos/itplr-kosit/validator-configuration-xrechnung/releases/latest" -UserAgent "Mozilla").assets | ? name -match "\.zip$"
Invoke-WebRequest $cfg.browser_download_url -OutFile "$env:TEMP\cfg.zip" -UseBasicParsing
Expand-Archive "$env:TEMP\cfg.zip" -DestinationPath $dest -Force
```
