"""FAZ 7: data_fetcher.py'nin sıfır ad set, sıfır harcama, eksik purchases
ve durum filtrelemesi senaryolarını doğru ele aldığını doğrular."""
import json

import pytest

import config
from data_fetcher import fetch_adset_performance


@pytest.fixture(autouse=True)
def _isolate_logs_dir(monkeypatch, tmp_path):
    # data_fetcher artık logs/actions.jsonl'den geçmiş okuyor
    # (recent_history); testlerin gerçek proje log'larını okumasını
    # engellemek için çalışma dizinini izole ediyoruz.
    monkeypatch.chdir(tmp_path)


class FakeClient:
    def __init__(self, adsets, insights_by_id, campaigns=None):
        self._adsets = adsets
        self._insights_by_id = insights_by_id
        self._campaigns = campaigns or []

    def get_adsets(self, campaign_id=None):
        return self._adsets

    def get_insights(self, object_id, date_preset="last_7d"):
        return self._insights_by_id.get(object_id, [])

    def get_campaigns(self):
        return self._campaigns


def test_no_adsets_returns_empty_snapshot():
    client = FakeClient(adsets=[], insights_by_id={})

    assert fetch_adset_performance(client) == []


def test_zero_spend_adset_is_skipped():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "0.00", "actions": []}]}
    client = FakeClient(adsets, insights)

    assert fetch_adset_performance(client) == []


def test_paused_adset_is_skipped_without_fetching_insights():
    adsets = [{"id": "1", "name": "A", "status": "PAUSED", "daily_budget": "2000", "campaign_id": "c1"}]

    class ExplodingInsightsClient(FakeClient):
        def get_insights(self, object_id, date_preset="last_7d"):
            raise AssertionError("PAUSED ad set için insight çekilmemeli")

    client = ExplodingInsightsClient(adsets, {})

    assert fetch_adset_performance(client) == []


def test_no_insight_data_is_skipped():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    client = FakeClient(adsets, insights_by_id={})  # "1" için hiç insight yok

    assert fetch_adset_performance(client) == []


def test_missing_purchases_defaults_to_zero():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "10.00", "actions": [{"action_type": "link_click", "value": "5"}]}]}
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    assert len(snapshot) == 1
    assert snapshot[0]["purchases"] == 0


def test_daily_budget_is_converted_from_minor_units():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "10.00", "actions": []}]}
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    assert snapshot[0]["daily_budget"] == 20.0


def test_multiple_active_adsets_all_included():
    adsets = [
        {"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"},
        {"id": "2", "name": "B", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c1"},
    ]
    insights = {
        "1": [{"spend": "10.00", "actions": [{"action_type": "purchase", "value": "2"}]}],
        "2": [{"spend": "5.00", "actions": []}],
    }
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    assert {row["adset_id"] for row in snapshot} == {"1", "2"}
    assert next(r for r in snapshot if r["adset_id"] == "1")["purchases"] == 2


def test_awareness_metrics_are_included_in_snapshot():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    insights = {
        "1": [
            {
                "spend": "10.00",
                "actions": [],
                "impressions": "50000",
                "reach": "30000",
                "frequency": "1.67",
                "cpm": "0.87",
            }
        ]
    }
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    row = snapshot[0]
    assert row["impressions"] == 50000
    assert row["reach"] == 30000
    assert row["frequency"] == 1.67
    assert row["cpm"] == 0.87


def test_missing_awareness_metrics_default_to_zero():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "2000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "10.00", "actions": []}]}
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    row = snapshot[0]
    assert row["impressions"] == 0
    assert row["reach"] == 0
    assert row["frequency"] == 0.0
    assert row["cpm"] == 0.0


def test_scope_filter_limits_to_matching_campaign(monkeypatch):
    monkeypatch.setattr(config.Config, "SCOPE_CAMPAIGN_NAME_FILTER", "pilot")
    campaigns = [
        {"id": "c1", "name": "Pilot Kampanyası"},
        {"id": "c2", "name": "Ana Kampanya"},
    ]
    adsets = [
        {"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c1"},
        {"id": "2", "name": "B", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c2"},
    ]
    insights = {
        "1": [{"spend": "10.00", "actions": []}],
        "2": [{"spend": "10.00", "actions": []}],
    }
    client = FakeClient(adsets, insights, campaigns=campaigns)

    snapshot = fetch_adset_performance(client)

    assert {row["adset_id"] for row in snapshot} == {"1"}


def test_no_scope_filter_includes_all_campaigns(monkeypatch):
    monkeypatch.setattr(config.Config, "SCOPE_CAMPAIGN_NAME_FILTER", "")
    adsets = [
        {"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c1"},
        {"id": "2", "name": "B", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c2"},
    ]
    insights = {
        "1": [{"spend": "10.00", "actions": []}],
        "2": [{"spend": "10.00", "actions": []}],
    }
    client = FakeClient(adsets, insights, campaigns=[])

    snapshot = fetch_adset_performance(client)

    assert {row["adset_id"] for row in snapshot} == {"1", "2"}


def test_recent_history_is_empty_when_no_logs():
    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "10.00", "actions": []}]}
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    assert snapshot[0]["recent_history"] == []


def test_recent_history_includes_past_actions_for_this_adset(tmp_path):
    from datetime import datetime, timezone

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    now = datetime.now(timezone.utc)
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": now.isoformat(), "adset_id": "1", "action": "update_budget",
            "status": "applied", "reason": "%50 azaltıldı",
        }) + "\n")
        f.write(json.dumps({
            "timestamp": now.isoformat(), "adset_id": "2", "action": "pause",
            "status": "applied", "reason": "başka ad set",
        }) + "\n")

    adsets = [{"id": "1", "name": "A", "status": "ACTIVE", "daily_budget": "1000", "campaign_id": "c1"}]
    insights = {"1": [{"spend": "10.00", "actions": []}]}
    client = FakeClient(adsets, insights)

    snapshot = fetch_adset_performance(client)

    history = snapshot[0]["recent_history"]
    assert len(history) == 1
    assert history[0]["reason"] == "%50 azaltıldı"
    assert history[0]["status"] == "uygulandı"
    assert history[0]["days_ago"] < 1
