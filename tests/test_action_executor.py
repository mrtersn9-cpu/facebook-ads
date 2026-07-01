"""FAZ 4: action_executor.py'nin DRY_RUN'da hiçbir gerçek çağrı yapmadığını
ve kısmi başarısızlıklarda durmadan devam edip her sonucu logladığını
doğrular. Gerçek Meta API'ye hiç dokunmaz."""
import json
import signal

import config
import action_executor
from action_executor import execute_actions
from meta_client import MetaAPIError


class ExplodingClient:
    """Çağrılırsa test'i patlatır — DRY_RUN'da hiç kullanılmamalı."""

    def update_adset_budget(self, *a, **k):
        raise AssertionError("DRY_RUN modunda gerçek API çağrısı yapılmamalı")

    def pause_entity(self, *a, **k):
        raise AssertionError("DRY_RUN modunda gerçek API çağrısı yapılmamalı")

    def activate_entity(self, *a, **k):
        raise AssertionError("DRY_RUN modunda gerçek API çağrısı yapılmamalı")


class PartialFailureClient:
    """5 aksiyondan bazıları başarılı, bazıları hata verir."""

    def pause_entity(self, adset_id):
        if adset_id == "fail-1":
            raise MetaAPIError("simulated failure")
        return {"success": True}

    def update_adset_budget(self, adset_id, cents):
        if adset_id == "fail-2":
            raise MetaAPIError("simulated failure")
        return {"success": True}

    def activate_entity(self, adset_id):
        return {"success": True}


def test_dry_run_never_calls_real_client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "DRY_RUN", True)

    actions = [
        {"adset_id": "1", "action": "pause", "reason": "test"},
        {"adset_id": "2", "action": "update_budget", "new_daily_budget": 10.0, "reason": "test"},
    ]

    summary = execute_actions(actions, client=ExplodingClient())

    assert summary == {"applied": 0, "dry_run": 2, "errors": 0}
    logged = (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(logged) == 2
    assert all(json.loads(line)["status"] == "dry_run" for line in logged)


def test_no_action_is_skipped_without_logging(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "DRY_RUN", True)

    summary = execute_actions([{"adset_id": "1", "action": "no_action", "reason": "test"}], client=ExplodingClient())

    assert summary == {"applied": 0, "dry_run": 0, "errors": 0}
    assert not (tmp_path / "logs" / "actions.jsonl").exists()


def test_partial_failures_continue_and_are_all_reported(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "DRY_RUN", False)

    actions = [
        {"adset_id": "ok-1", "action": "pause", "reason": "test"},
        {"adset_id": "fail-1", "action": "pause", "reason": "test"},
        {"adset_id": "ok-2", "action": "update_budget", "new_daily_budget": 10.0, "reason": "test"},
        {"adset_id": "fail-2", "action": "update_budget", "new_daily_budget": 10.0, "reason": "test"},
        {"adset_id": "ok-3", "action": "activate", "reason": "test"},
    ]

    summary = execute_actions(actions, client=PartialFailureClient())

    assert summary == {"applied": 3, "dry_run": 0, "errors": 2}
    logged = [json.loads(line) for line in (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    assert len(logged) == 5
    statuses = {entry["adset_id"]: entry["status"] for entry in logged}
    assert statuses["ok-1"] == "applied"
    assert statuses["fail-1"] == "error"
    assert statuses["ok-2"] == "applied"
    assert statuses["fail-2"] == "error"
    assert statuses["ok-3"] == "applied"


def test_shutdown_flag_stops_before_next_action_but_keeps_prior_results(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "DRY_RUN", True)
    monkeypatch.setattr(action_executor, "_shutdown_requested", True)

    actions = [
        {"adset_id": "1", "action": "pause", "reason": "test"},
        {"adset_id": "2", "action": "pause", "reason": "test"},
    ]

    summary = execute_actions(actions, client=ExplodingClient())

    assert summary == {"applied": 0, "dry_run": 0, "errors": 0}
    logged = [json.loads(line) for line in (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    assert len(logged) == 1
    assert logged[0]["status"] == "shutdown"


def test_install_signal_handlers_registers_sigint_and_sigterm():
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    try:
        action_executor.install_signal_handlers()
        assert signal.getsignal(signal.SIGINT) is action_executor._handle_shutdown_signal
        assert signal.getsignal(signal.SIGTERM) is action_executor._handle_shutdown_signal
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


def test_handle_shutdown_signal_sets_flag(monkeypatch):
    monkeypatch.setattr(action_executor, "_shutdown_requested", False)
    action_executor._handle_shutdown_signal(signal.SIGINT, None)
    assert action_executor._shutdown_requested is True
