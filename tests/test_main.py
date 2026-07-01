"""FAZ 5: kill switch ve scheduler dayanıklılığı testleri."""
import json

import config
import main
from guardrails import GuardrailViolation


def test_kill_switch_exits_without_any_call(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", True)

    def boom():
        raise AssertionError("KILL_SWITCH aktifken hiçbir dış çağrı yapılmamalı")

    monkeypatch.setattr(main, "fetch_adset_performance", boom)

    main.run_once()  # patlamamalı


def test_safe_run_once_does_not_propagate_exceptions(monkeypatch):
    def boom():
        raise RuntimeError("decision_engine patladı")

    monkeypatch.setattr(main, "run_once", boom)

    main._safe_run_once()  # patlamamalı, sadece loglanmalı


def test_kill_switch_off_still_reaches_fetch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    monkeypatch.setattr(config.Config, "ANTHROPIC_API_KEY", "fake")

    called = {"fetch": False}

    def fake_fetch():
        called["fetch"] = True
        return []

    monkeypatch.setattr(main, "fetch_adset_performance", fake_fetch)

    main.run_once()

    assert called["fetch"] is True


def test_guardrail_violation_always_notifies(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(main, "fetch_adset_performance", lambda: [{"adset_id": "1", "spend": 10, "daily_budget": 5}])
    monkeypatch.setattr(main, "get_action_recommendations", lambda snapshot: [])

    def raise_violation(actions, snapshot):
        raise GuardrailViolation("toplam bütçe aşıldı")

    monkeypatch.setattr(main, "apply_guardrails", raise_violation)

    notified = {}
    monkeypatch.setattr(main, "notify_guardrail_violation", lambda msg: notified.setdefault("msg", msg))

    monkeypatch.setattr(config.Config, "validate", classmethod(lambda cls: None))

    main.run_once()

    assert notified.get("msg") == "toplam bütçe aşıldı"
