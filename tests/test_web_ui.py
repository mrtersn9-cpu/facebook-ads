"""Web dashboard'unun read-only sayfasını ve /run uçlarının doğru script'i
tetiklediğini doğrular. subprocess.run monkeypatch ile sahtelenir — testler
gerçek main.py/run_creative_pipeline.py'yi hiç çalıştırmaz, dolayısıyla
gerçek Meta hesabına hiç dokunmaz."""
import json

import pytest

import web_ui


@pytest.fixture
def client():
    web_ui.app.config["TESTING"] = True
    web_ui._last_run_result = None
    with web_ui.app.test_client() as c:
        yield c


def _write_log(tmp_path, entries):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_dashboard_renders_config_status(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"DRY_RUN" in resp.data
    assert b"KILL_SWITCH" in resp.data


def test_dashboard_shows_log_entries(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_log(
        tmp_path,
        [{"timestamp": "2026-01-01T00:00:00+00:00", "adset_id": "42", "action": "pause", "status": "dry_run", "reason": "test gerekcesi"}],
    )

    resp = client.get("/")

    assert b"42" in resp.data
    assert b"test gerekcesi" in resp.data


def test_dashboard_handles_missing_log_file(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Henüz log kaydı yok".encode("utf-8") in resp.data


def test_run_main_invokes_main_py_via_subprocess(client, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeCompletedProcess:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return FakeCompletedProcess()

    monkeypatch.setattr(web_ui.subprocess, "run", fake_run)

    resp = client.post("/run/main")

    assert resp.status_code == 302
    assert captured["cmd"][1:] == ["main.py", "--once"]
    assert web_ui._last_run_result["exit_code"] == 0


def test_run_creative_invokes_creative_pipeline_via_subprocess(client, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "boom"

        return FakeCompletedProcess()

    monkeypatch.setattr(web_ui.subprocess, "run", fake_run)

    resp = client.post("/run/creative")

    assert resp.status_code == 302
    assert captured["cmd"][1:] == ["run_creative_pipeline.py", "--once"]
    assert web_ui._last_run_result["exit_code"] == 1
    assert web_ui._last_run_result["stderr"] == "boom"


def test_last_run_result_displayed_after_run(client, monkeypatch):
    def fake_run(cmd, **kwargs):
        class FakeCompletedProcess:
            returncode = 0
            stdout = "calistirma ozeti"
            stderr = ""

        return FakeCompletedProcess()

    monkeypatch.setattr(web_ui.subprocess, "run", fake_run)

    client.post("/run/main")
    resp = client.get("/")

    assert b"calistirma ozeti" in resp.data
