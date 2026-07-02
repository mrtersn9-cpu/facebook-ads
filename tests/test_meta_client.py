"""FAZ 1: mock mod, pagination ve hata sınıflandırması testleri.

Bu testler gerçek Meta API'ye hiç dokunmaz; requests.get/post monkeypatch
ile sahtelenir.
"""
import json
import time

import pytest

import config
import meta_client
from meta_client import MetaClient, check_token_expiry


class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json_data


@pytest.fixture
def real_mode(monkeypatch):
    """Mock modu kapatıp sahte kimlik bilgileriyle gerçek-API kod yolunu test eder."""
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", False)
    monkeypatch.setattr(config.Config, "META_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(config.Config, "META_AD_ACCOUNT_ID", "123")
    monkeypatch.setattr(meta_client.time, "sleep", lambda seconds: None)


def test_mock_mode_returns_fixture_campaigns(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    campaigns = client.get_campaigns()

    assert len(campaigns) == 2
    assert campaigns[0]["id"] == "6001"


def test_mock_mode_returns_fixture_adsets_filtered_by_campaign(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    all_adsets = client.get_adsets()
    campaign_adsets = client.get_adsets(campaign_id="6001")

    assert len(all_adsets) == 5
    assert {a["id"] for a in campaign_adsets} == {"7001", "7002"}


def test_mock_mode_returns_fixture_insights_or_empty(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    assert client.get_insights("7001")[0]["spend"] == "45.32"
    assert client.get_insights("unknown-adset-id") == []


def test_auth_error_does_not_retry(real_mode, monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return FakeResponse(400, {"error": {"code": 190, "message": "Invalid OAuth access token"}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    client = MetaClient()
    with pytest.raises(meta_client.MetaAuthError):
        client.get_campaigns()

    assert calls["count"] == 1, "Auth hatasında retry döngüsüne girilmemeli"


def test_rate_limit_retries_then_raises(real_mode, monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return FakeResponse(400, {"error": {"code": 4, "message": "Application request limit reached"}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    client = MetaClient()
    with pytest.raises(meta_client.MetaRateLimitError):
        client.get_campaigns()

    assert calls["count"] == meta_client.MAX_RETRIES + 1


def test_rate_limit_succeeds_after_transient_failures(real_mode, monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            return FakeResponse(400, {"error": {"code": 17, "message": "User request limit reached"}})
        return FakeResponse(200, {"data": [{"id": "6001"}]})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    client = MetaClient()
    campaigns = client.get_campaigns()

    assert campaigns == [{"id": "6001"}]
    assert calls["count"] == 3


def test_pagination_merges_all_pages(real_mode, monkeypatch):
    page1 = FakeResponse(
        200,
        {
            "data": [{"id": "1"}],
            "paging": {"next": "https://graph.facebook.com/v25.0/act_123/campaigns?after=abc"},
        },
    )
    page2 = FakeResponse(200, {"data": [{"id": "2"}], "paging": {}})
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return page1 if calls["count"] == 1 else page2

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    client = MetaClient()
    campaigns = client.get_campaigns()

    assert [c["id"] for c in campaigns] == ["1", "2"]
    assert calls["count"] == 2


def test_check_token_expiry_noop_in_mock_mode(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)

    def boom(*a, **k):
        raise AssertionError("Mock modda debug_token çağrılmamalı")

    monkeypatch.setattr(meta_client.requests, "get", boom)

    check_token_expiry()  # patlamamalı


def test_check_token_expiry_warns_when_close_to_expiring(real_mode, monkeypatch, caplog):
    monkeypatch.setattr(config.Config, "TOKEN_EXPIRY_WARN_DAYS", 7)
    soon = time.time() + 2 * 86400  # 2 gün sonra

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(200, {"data": {"expires_at": soon}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    with caplog.at_level("WARNING"):
        check_token_expiry()

    assert any("sona erecek" in record.message for record in caplog.records)


def test_check_token_expiry_silent_when_far_from_expiring(real_mode, monkeypatch, caplog):
    monkeypatch.setattr(config.Config, "TOKEN_EXPIRY_WARN_DAYS", 7)
    far_future = time.time() + 90 * 86400

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(200, {"data": {"expires_at": far_future}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    with caplog.at_level("WARNING"):
        check_token_expiry()

    assert caplog.records == []


def test_check_token_expiry_silent_when_never_expires(real_mode, monkeypatch, caplog):
    def fake_get(url, params=None, timeout=None):
        return FakeResponse(200, {"data": {"expires_at": 0}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    with caplog.at_level("WARNING"):
        check_token_expiry()

    assert caplog.records == []


def test_check_token_expiry_logs_and_swallows_api_error(real_mode, monkeypatch, caplog):
    def fake_get(url, params=None, timeout=None):
        return FakeResponse(400, {"error": {"code": 190, "message": "Invalid token"}})

    monkeypatch.setattr(meta_client.requests, "get", fake_get)

    with caplog.at_level("WARNING"):
        check_token_expiry()  # patlamamalı

    assert any("başarısız" in record.message for record in caplog.records)


# --- FAZ 12: yeni kampanya/ad set/creative/reklam oluşturma ---


def test_create_campaign_mock_mode_is_always_paused(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    campaign = client.create_campaign(name="Test Kampanya", objective="OUTCOME_ENGAGEMENT")

    assert campaign["status"] == "PAUSED"
    assert campaign["id"]


def test_create_campaign_defaults_special_ad_categories_to_none(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    campaign = client.create_campaign(name="Test Kampanya", objective="OUTCOME_ENGAGEMENT")

    assert campaign["special_ad_categories"] == ["NONE"]


def test_create_adset_mock_mode_is_always_paused(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    adset = client.create_adset(campaign_id="c1", name="Test Adset", daily_budget_cents=1000, targeting={})

    assert adset["status"] == "PAUSED"


def test_create_ad_mock_mode_is_always_paused(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    ad = client.create_ad(adset_id="a1", creative_id="cr1", name="Test Ad")

    assert ad["status"] == "PAUSED"


def test_create_ad_creative_mock_mode_uses_source_instagram_media_id(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    creative = client.create_ad_creative(name="Test Creative", instagram_media_id="ig_media_1")

    assert creative["source_instagram_media_id"] == "ig_media_1"


def test_create_ad_creative_real_mode_sends_source_instagram_media_id(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_creative_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_ad_creative(name="Test Creative", instagram_media_id="ig_media_1")

    assert captured["source_instagram_media_id"] == "ig_media_1"
    assert "object_story_id" not in captured


def test_create_campaign_real_mode_sends_paused_status(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_campaign_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_campaign(name="Test", objective="OUTCOME_ENGAGEMENT")

    assert captured["status"] == "PAUSED"
    assert json.loads(captured["special_ad_categories"]) == ["NONE"]
    assert captured["is_adset_budget_sharing_enabled"] is False


def test_create_adset_real_mode_sends_paused_status(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_adset_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_adset(campaign_id="c1", name="Test", daily_budget_cents=1000, targeting={"geo_locations": {}})

    assert captured["status"] == "PAUSED"
    assert captured["optimization_goal"] == "IMPRESSIONS"
    assert captured["billing_event"] == "IMPRESSIONS"
    assert captured["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert "destination_type" not in captured


def test_create_adset_omits_destination_type_by_default(monkeypatch):
    monkeypatch.setattr(config.Config, "META_MOCK_MODE", True)
    client = MetaClient()

    adset = client.create_adset(campaign_id="c1", name="Test", daily_budget_cents=1000, targeting={})

    assert "destination_type" not in adset


def test_create_adset_real_mode_sends_destination_type_when_given(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_adset_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_adset(
        campaign_id="c1",
        name="Test",
        daily_budget_cents=1000,
        targeting={},
        optimization_goal="CONVERSATIONS",
        destination_type="INSTAGRAM_DIRECT",
    )

    assert captured["destination_type"] == "INSTAGRAM_DIRECT"
    assert captured["optimization_goal"] == "CONVERSATIONS"


def test_create_ad_creative_real_mode_omits_cta_by_default(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_creative_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_ad_creative(name="Test", instagram_media_id="ig_media_1")

    assert "call_to_action" not in captured


def test_create_ad_creative_real_mode_sends_call_to_action_when_given(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_creative_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_ad_creative(name="Test", instagram_media_id="ig_media_1", call_to_action_type="MESSAGE_PAGE")

    assert json.loads(captured["call_to_action"]) == {"type": "MESSAGE_PAGE"}


def test_create_ad_creative_real_mode_includes_link_when_given(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_creative_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_ad_creative(
        name="Test",
        instagram_media_id="ig_media_1",
        call_to_action_type="MESSAGE_PAGE",
        call_to_action_link="https://ig.me/m/sonuc_yayinlari",
    )

    assert json.loads(captured["call_to_action"]) == {
        "type": "MESSAGE_PAGE",
        "value": {"link": "https://ig.me/m/sonuc_yayinlari"},
    }


def test_create_ad_real_mode_sends_paused_status(real_mode, monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return FakeResponse(200, {"id": "real_ad_1"})

    monkeypatch.setattr(meta_client.requests, "post", fake_post)

    client = MetaClient()
    client.create_ad(adset_id="a1", creative_id="cr1", name="Test")

    assert captured["status"] == "PAUSED"


def test_create_methods_have_no_overridable_status_parameter():
    client = MetaClient()

    with pytest.raises(TypeError):
        client.create_campaign(name="x", objective="y", status="ACTIVE")

    with pytest.raises(TypeError):
        client.create_adset(campaign_id="c1", name="x", daily_budget_cents=1, targeting={}, status="ACTIVE")

    with pytest.raises(TypeError):
        client.create_ad(adset_id="a1", creative_id="cr1", name="x", status="ACTIVE")
