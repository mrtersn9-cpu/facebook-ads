"""FAZ 3: guardrail'lerin gerçekten fail-closed davrandığını kanıtlayan
testler. Tamamen izole — gerçek Meta/Anthropic API'ye hiç dokunmaz."""
import pytest

import config
from guardrails import GuardrailViolation, apply_guardrails

SNAPSHOT = [
    {"adset_id": "1", "name": "Adset 1", "daily_budget": 20.0, "spend": 50.0, "purchases": 3},
    {"adset_id": "2", "name": "Adset 2", "daily_budget": 15.0, "spend": 2.0, "purchases": 0},
    {"adset_id": "3", "name": "Adset 3", "daily_budget": 10.0, "spend": 30.0, "purchases": 1},
]


@pytest.fixture(autouse=True)
def guardrail_constants(monkeypatch):
    monkeypatch.setattr(config.Config, "MAX_BUDGET_CHANGE_PERCENT", 20.0)
    monkeypatch.setattr(config.Config, "MIN_SPEND_BEFORE_ACTION", 5.0)
    monkeypatch.setattr(config.Config, "MAX_DAILY_BUDGET_TOTAL", 1000.0)
    monkeypatch.setattr(config.Config, "MAX_ACTIONS_PER_RUN", 10)


def test_unknown_adset_id_is_rejected():
    actions = [{"adset_id": "does-not-exist", "action": "pause", "reason": "test"}]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert approved == []
    assert len(rejected) == 1
    assert "Bilinmeyen" in rejected[0]["rejection_reason"]


def test_action_below_min_spend_is_rejected_except_pause():
    actions = [
        {"adset_id": "2", "action": "update_budget", "new_daily_budget": 20.0, "reason": "test"},
        {"adset_id": "2", "action": "pause", "reason": "test"},
    ]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert len(rejected) == 1
    assert rejected[0]["action"] == "update_budget"
    assert "Minimum harcama" in rejected[0]["rejection_reason"]
    assert len(approved) == 1
    assert approved[0]["action"] == "pause"


def test_budget_change_exceeding_percent_is_clamped():
    # adset 1: current 20.0, +20% max -> upper bound 24.0. Öneri 40.0 kırpılmalı.
    actions = [{"adset_id": "1", "action": "update_budget", "new_daily_budget": 40.0, "reason": "test"}]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert rejected == []
    assert approved[0]["new_daily_budget"] == pytest.approx(24.0)


def test_budget_decrease_exceeding_percent_is_clamped_to_lower_bound():
    # adset 1: current 20.0, -20% max -> lower bound 16.0. Öneri 1.0 kırpılmalı.
    actions = [{"adset_id": "1", "action": "update_budget", "new_daily_budget": 1.0, "reason": "test"}]

    approved, _ = apply_guardrails(actions, SNAPSHOT)

    assert approved[0]["new_daily_budget"] == pytest.approx(16.0)


def test_total_budget_over_cap_raises_and_blocks_everything(monkeypatch):
    monkeypatch.setattr(config.Config, "MAX_DAILY_BUDGET_TOTAL", 30.0)
    actions = [
        {"adset_id": "1", "action": "update_budget", "new_daily_budget": 24.0, "reason": "test"},
        {"adset_id": "3", "action": "update_budget", "new_daily_budget": 12.0, "reason": "test"},
    ]

    with pytest.raises(GuardrailViolation):
        apply_guardrails(actions, SNAPSHOT)


def test_actions_beyond_max_per_run_are_truncated(monkeypatch):
    monkeypatch.setattr(config.Config, "MAX_ACTIONS_PER_RUN", 2)
    actions = [
        {"adset_id": "1", "action": "pause", "reason": "1"},
        {"adset_id": "2", "action": "pause", "reason": "2"},
        {"adset_id": "3", "action": "pause", "reason": "3"},
    ]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert len(approved) + len(rejected) == 2
    assert not any(a["adset_id"] == "3" for a in approved + rejected)


def test_disallowed_action_type_is_rejected():
    actions = [{"adset_id": "1", "action": "delete_campaign", "reason": "test"}]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert approved == []
    assert "Bilinmeyen aksiyon" in rejected[0]["rejection_reason"]


def test_empty_reason_is_rejected():
    actions = [{"adset_id": "1", "action": "pause", "reason": ""}]

    approved, rejected = apply_guardrails(actions, SNAPSHOT)

    assert approved == []
    assert "reason" in rejected[0]["rejection_reason"]
