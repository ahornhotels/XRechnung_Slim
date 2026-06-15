"""
core/crypto.py
--------------
Fernet AES-128 Symmetric Encryption fuer sensitive Config-Werte.
Schluessel liegt in separater .key-Datei (NTFS-ACL only Service-User).
"""
from pathlib import Path
from cryptography.fernet import Fernet


def generate_key_file(path: Path) -> None:
    """Generiert einen neuen Fernet-Key und schreibt ihn nach <path>."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet.generate_key())


def load_key(path: Path) -> bytes:
    """Liest einen Fernet-Key aus einer Datei."""
    return Path(path).read_bytes()


def encrypt(plaintext: str, key: bytes) -> str:
    """Verschluesselt einen String, gibt das Token als Str zurueck."""
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str, key: bytes) -> str:
    """Entschluesselt einen Token-String zurueck zu Klartext."""
    return Fernet(key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
