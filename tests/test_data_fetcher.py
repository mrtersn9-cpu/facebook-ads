"""FAZ 7: data_fetcher.py'nin sıfır ad set, sıfır harcama, eksik purchases
ve durum filtrelemesi senaryolarını doğru ele aldığını doğrular."""
from data_fetcher import fetch_adset_performance


class FakeClient:
    def __init__(self, adsets, insights_by_id):
        self._adsets = adsets
        self._insights_by_id = insights_by_id

    def get_adsets(self, campaign_id=None):
        return self._adsets

    def get_insights(self, object_id, date_preset="last_7d"):
        return self._insights_by_id.get(object_id, [])


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
