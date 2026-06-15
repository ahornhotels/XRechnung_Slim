"""Verifiziert, dass SUITE8_CONFIG_DIR den config_loader-CONFIG_DIR umlenkt."""
import importlib
import os
from pathlib import Path

import pytest


def test_env_var_overrides_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SUITE8_CONFIG_DIR", str(tmp_path))
    import core.config_loader as cl
    importlib.reload(cl)
    assert Path(cl.CONFIG_DIR) == tmp_path


def test_default_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("SUITE8_CONFIG_DIR", raising=False)
    import core.config_loader as cl
    importlib.reload(cl)
    expected = Path(cl.__file__).resolve().parent.parent / "config"
    assert Path(cl.CONFIG_DIR) == expected
