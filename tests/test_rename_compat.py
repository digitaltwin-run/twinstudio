from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import twinstudio


def test_product_identity_and_legacy_namespace() -> None:
    assert twinstudio.__product__ == "TwinStudio"
    assert twinstudio.__version__ == "0.5.0"
    code = r'''
import warnings
warnings.simplefilter('always')
with warnings.catch_warnings(record=True) as caught:
    import living_product_studio
    from living_product_studio.domain import ProjectSnapshot
assert living_product_studio.__product__ == 'TwinStudio'
assert ProjectSnapshot.__module__ == 'twinstudio.domain'
assert any(item.category is DeprecationWarning for item in caught)
'''
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_settings_prefer_new_names_and_accept_legacy_fallback(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    code = r'''
from twinstudio.settings import settings
print(settings.data_dir)
print(settings.port)
'''
    base = os.environ.copy()
    base["PYTHONPATH"] = str(root / "src")
    # Keep the subprocess contract test independent from a developer's local .env.
    base["PYTHON_DOTENV_DISABLED"] = "1"
    for key in ["TWINSTUDIO_DATA_DIR", "LPS_DATA_DIR", "TWINSTUDIO_PORT", "LPS_PORT"]:
        base.pop(key, None)

    new_env = base | {
        "TWINSTUDIO_DATA_DIR": str(tmp_path / "new"),
        "LPS_DATA_DIR": str(tmp_path / "old"),
        "TWINSTUDIO_PORT": "8123",
        "LPS_PORT": "8124",
    }
    new = subprocess.run([sys.executable, "-c", code], cwd=root, env=new_env, text=True, capture_output=True)
    assert new.returncode == 0, new.stderr
    assert str(tmp_path / "new") in new.stdout
    assert "8123" in new.stdout

    legacy_env = base | {"LPS_DATA_DIR": str(tmp_path / "legacy"), "LPS_PORT": "8125"}
    legacy = subprocess.run([sys.executable, "-c", code], cwd=root, env=legacy_env, text=True, capture_output=True)
    assert legacy.returncode == 0, legacy.stderr
    assert str(tmp_path / "legacy") in legacy.stdout
    assert "8125" in legacy.stdout
