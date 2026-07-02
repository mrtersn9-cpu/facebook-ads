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


def test_run_once_checks_token_expiry_before_fetching(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    monkeypatch.setattr(config.Config, "ANTHROPIC_API_KEY", "fake")

    called = {"expiry_checked": False}
    monkeypatch.setattr(main, "check_token_expiry", lambda: called.__setitem__("expiry_checked", True))
    monkeypatch.setattr(main, "fetch_adset_performance", lambda: [])

    main.run_once()

    assert called["expiry_checked"] is True


def test_kill_switch_skips_token_expiry_check(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", True)

    def boom():
        raise AssertionError("KILL_SWITCH aktifken token expiry kontrolü yapılmamalı")

    monkeypatch.setattr(main, "check_token_expiry", boom)

    main.run_once()  # patlamamalı


def test_automation_mode_onayli_queues_instead_of_executing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(config.Config, "AUTOMATION_MODE", "onayli")
    monkeypatch.setattr(main, "check_token_expiry", lambda: None)
    monkeypatch.setattr(config.Config, "validate", classmethod(lambda cls: None))
    monkeypatch.setattr(main, "fetch_adset_performance", lambda: [{"adset_id": "1", "spend": 10, "daily_budget": 5}])

    actions = [
        {"adset_id": "1", "action": "pause", "reason": "zayıf performans"},
        {"adset_id": "2", "action": "no_action", "reason": "yeterli veri yok"},
    ]
    monkeypatch.setattr(main, "get_action_recommendations", lambda snapshot: actions)
    monkeypatch.setattr(main, "apply_guardrails", lambda actions, snapshot: (actions, []))

    def boom(*a, **k):
        raise AssertionError("AUTOMATION_MODE=onayli iken execute_actions çağrılmamalı")

    monkeypatch.setattr(main, "execute_actions", boom)

    queued = []
    monkeypatch.setattr(main, "queue_action", lambda action: queued.append(action))

    notified = {}
    monkeypatch.setattr(
        main,
        "notify_queued_for_approval",
        lambda queued_count, proposed_count, rejected_count: notified.update(
            queued=queued_count, proposed=proposed_count, rejected=rejected_count
        ),
    )

    main.run_once()

    assert [a["adset_id"] for a in queued] == ["1"]  # no_action kuyruğa girmemeli
    assert notified == {"queued": 1, "proposed": 2, "rejected": 0}


def test_automation_mode_tam_otomatik_executes_directly(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(config.Config, "AUTOMATION_MODE", "tam_otomatik")
    monkeypatch.setattr(main, "check_token_expiry", lambda: None)
    monkeypatch.setattr(config.Config, "validate", classmethod(lambda cls: None))
    monkeypatch.setattr(main, "fetch_adset_performance", lambda: [{"adset_id": "1", "spend": 10, "daily_budget": 5}])

    actions = [{"adset_id": "1", "action": "pause", "reason": "zayıf performans"}]
    monkeypatch.setattr(main, "get_action_recommendations", lambda snapshot: actions)
    monkeypatch.setattr(main, "apply_guardrails", lambda actions, snapshot: (actions, []))

    def boom(action):
        raise AssertionError("AUTOMATION_MODE=tam_otomatik iken queue_action çağrılmamalı")

    monkeypatch.setattr(main, "queue_action", boom)

    executed = {}

    def fake_execute_actions(approved):
        executed["approved"] = approved
        return {"applied": 1, "dry_run": 0, "no_action": 0, "errors": 0}

    monkeypatch.setattr(main, "execute_actions", fake_execute_actions)

    notified = {}
    monkeypatch.setattr(
        main,
        "notify_run_summary",
        lambda summary, proposed_count, rejected_count: notified.update(summary=summary),
    )

    main.run_once()

    assert executed["approved"] == actions
    assert notified["summary"]["applied"] == 1


def test_guardrail_violation_always_notifies(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(main, "check_token_expiry", lambda: None)
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
