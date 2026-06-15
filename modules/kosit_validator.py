"""
modules/kosit_validator.py
--------------------------
Wrapper um KoSIT-Validator-JAR (Schematron + erweiterte Regeln fuer XRechnung).
Aufruf via Java-Subprocess. JAR und Konfig liegen in validation/xrechnung-X.Y.Z/.

Falls JAR nicht installiert: validate() wirft FileNotFoundError. Caller
sollte das catchen wenn 'kosit_validation' in app_settings auf False steht.
"""
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from lxml import etree

logger = logging.getLogger(__name__)

VALIDATION_DIR = Path(__file__).resolve().parent.parent / "validation"
BUNDLED_JRE_DIR = Path(__file__).resolve().parent.parent / "install" / "jre"


class KositValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("KoSIT-Validierung fehlgeschlagen:\n" + "\n".join(errors))


def _resolve_java() -> str:
    """Findet java.exe. Sucht in dieser Reihenfolge:
    1. install/jre/bin/java.exe (mit dem Installer gebuendelte JRE)
    2. java im PATH (System-Java)

    Wirft FileNotFoundError wenn nichts gefunden wird.
    """
    bundled = BUNDLED_JRE_DIR / "bin" / "java.exe"
    if bundled.exists():
        return str(bundled)
    java = shutil.which("java")
    if not java:
        raise FileNotFoundError(
            "java nicht gefunden. Erwarte install/jre/bin/java.exe (gebuendelte JRE) "
            "oder 'java' im PATH (JRE >= 11)."
        )
    return java


def validate(xml_bytes: bytes, version: str = "3.0.2") -> None:
    """Validiert XML via KoSIT-JAR.

    Args:
        xml_bytes: Das zu pruefende XRechnung-XML
        version: XRechnung-Version, bestimmt Subverzeichnis in validation/

    Raises:
        FileNotFoundError: wenn JAR oder scenarios.xml fehlen
        KositValidationError: wenn Validator Fehler findet (mit Liste der Meldungen)
    """
    base = VALIDATION_DIR / f"xrechnung-{version}"
    jar = base / "kosit-validator.jar"
    scenarios = base / "scenarios.xml"

    if not jar.exists():
        raise FileNotFoundError(f"KoSIT-JAR nicht gefunden: {jar}")
    if not scenarios.exists():
        raise FileNotFoundError(f"KoSIT scenarios.xml nicht gefunden: {scenarios}")

    java = _resolve_java()

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        in_file = tmp / "invoice.xml"
        in_file.write_bytes(xml_bytes)

        try:
            # input='' fuettert eine leere stdin-Pipe - KoSIT ruft sonst
            # FileInputStream.available0() auf NUL-Device auf was unter Windows
            # mit "Unzulaessige Funktion" knallt.
            result = subprocess.run(
                [java, "-jar", str(jar), "-s", str(scenarios), "-o", str(tmp), str(in_file)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(base),
                input="",
            )
        except subprocess.TimeoutExpired:
            raise KositValidationError(["KoSIT-Validator Timeout nach 60s"])

        report_file = tmp / "invoice-report.xml"
        if not report_file.exists():
            stderr_excerpt = (result.stderr or "")[:500]
            raise KositValidationError([
                f"KoSIT-Report nicht erzeugt. Exit={result.returncode}. stderr={stderr_excerpt}"
            ])

        try:
            report = etree.parse(str(report_file))
        except etree.XMLSyntaxError as e:
            raise KositValidationError([f"KoSIT-Report nicht parsebar: {e}"])

        # KoSIT-Report: Root-Element <rep:report valid="true|false">
        # Bei valid="false" muessen Details ausgelesen werden. Fehler kommen aus
        # mehreren Quellen: schemaValidationError, message[level=error], failed-assert,
        # oder noScenarioMatched.
        root = report.getroot()
        valid_attr = root.get("valid", "true").lower()
        if valid_attr == "true":
            return

        ns = {
            "rep": "http://www.xoev.de/de/validator/varl/1",
            "svrl": "http://purl.oclc.org/dsdl/svrl",
        }
        errors: list[str] = []

        # 1. Schema-Validierungs-Fehler
        for sv in report.xpath("//rep:schemaValidationError/rep:errorMessage", namespaces=ns):
            errors.append(f"Schema: {(sv.text or '').strip()}")

        # 2. Schematron failed-asserts (Business Rules)
        for fa in report.xpath("//svrl:failed-assert", namespaces=ns):
            text = " ".join(t.strip() for t in fa.itertext() if t.strip())[:400]
            errors.append(f"Schematron: {text}")

        # 3. message-Elemente mit level=error (Acceptance-Phase)
        for m in report.xpath("//rep:message[@level='error']", namespaces=ns):
            code = m.get("code", "")
            text = (m.text or "").strip()[:400]
            errors.append(f"Acceptance {code}: {text}")

        # 4. noScenarioMatched
        if report.xpath("//rep:noScenarioMatched", namespaces=ns):
            errors.append("Kein Szenario gematched - CustomizationID/Namespace pruefen")

        if not errors:
            # Fallback: irgendetwas ist falsch, aber keine spezifische Meldung
            errors.append(f"Validierung fehlgeschlagen (valid={valid_attr}), aber keine Detail-Meldungen gefunden")
        raise KositValidationError(errors)
