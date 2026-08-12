from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev_server.sh"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _server_env(tmp_path: Path, port: int) -> dict[str, str]:
    return {
        **os.environ,
        "TWINSTUDIO_HOST": "127.0.0.1",
        "TWINSTUDIO_PORT": str(port),
        "TWINSTUDIO_RUN_DIR": str(tmp_path / "run"),
        "TWINSTUDIO_DATA_DIR": str(tmp_path / "data"),
        "TWINSTUDIO_PROJECT_ROOT": str(ROOT),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'server.db'}",
        "MQTT_ENABLED": "false",
    }


def _control(action: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), action],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_makefile_exposes_local_lifecycle_controls() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("start:", "restart recreate:", "stop kill:", "status:", "health:"):
        assert target in makefile
    assert "scripts/dev_server.sh" in makefile
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'nohup setsid --fork "$cli_bin" serve' in script
    assert "server_pid" in script


def test_start_replaces_owned_instance_and_stop_cleans_it_up(tmp_path: Path) -> None:
    port = _free_port()
    run_dir = tmp_path / "run"
    env = _server_env(tmp_path, port)

    try:
        first = _control("start", env)
        assert first.returncode == 0, first.stderr
        first_pid = int((run_dir / "twinstudio.pid").read_text().strip())
        assert httpx.get(f"http://127.0.0.1:{port}/health").json()["status"] == "ok"

        second = _control("start", env)
        assert second.returncode == 0, second.stderr
        second_pid = int((run_dir / "twinstudio.pid").read_text().strip())
        assert second_pid != first_pid
        assert "Stopping TwinStudio PID(s)" in second.stdout
        assert _control("status", env).returncode == 0
    finally:
        stopped = _control("stop", env)
        assert stopped.returncode == 0, stopped.stderr
    assert not (run_dir / "twinstudio.pid").exists()


def test_start_refuses_to_kill_an_unrelated_port_owner(tmp_path: Path) -> None:
    port = _free_port()
    env = _server_env(tmp_path, port)
    foreign = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if foreign.poll() is not None:
                raise AssertionError("foreign test server exited unexpectedly")
            try:
                if httpx.get(f"http://127.0.0.1:{port}", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        result = _control("start", env)
        assert result.returncode != 0
        assert "refusing to kill unrelated PID" in result.stderr
        assert foreign.poll() is None
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)
