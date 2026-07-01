"""FAZ 11: ig_client.py'nin mock modu ve hata sınıflandırmasını doğrular.
Gerçek Instagram/Meta API'ye hiç dokunmaz."""
import json

import pytest

import config
import ig_client
from ig_client import IGClient


class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json_data


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", False)
    monkeypatch.setattr(config.Config, "IG_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(ig_client.time, "sleep", lambda seconds: None)


def test_mock_mode_returns_fixture_media(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", True)
    client = IGClient()

    media = client.get_recent_media("ig-user-1")

    assert len(media) == 4
    assert media[0]["id"] == "ig_media_1"


def test_mock_mode_respects_limit(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", True)
    client = IGClient()

    media = client.get_recent_media("ig-user-1", limit=2)

    assert len(media) == 2


def test_mock_mode_returns_fixture_insights(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", True)
    client = IGClient()

    insights = client.get_media_insights("ig_media_1")

    assert insights == {"reach": 8000, "saved": 30}


def test_mock_mode_unknown_media_returns_empty_insights(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", True)
    client = IGClient()

    assert client.get_media_insights("unknown") == {}


def test_auth_error_does_not_retry(real_mode, monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return FakeResponse(400, {"error": {"code": 190, "message": "Invalid token"}})

    monkeypatch.setattr(ig_client.requests, "get", fake_get)

    client = IGClient()
    with pytest.raises(ig_client.IGAuthError):
        client.get_recent_media("ig-user-1")

    assert calls["count"] == 1


def test_rate_limit_retries_then_raises(real_mode, monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return FakeResponse(400, {"error": {"code": 4, "message": "rate limited"}})

    monkeypatch.setattr(ig_client.requests, "get", fake_get)

    client = IGClient()
    with pytest.raises(ig_client.IGRateLimitError):
        client.get_recent_media("ig-user-1")

    assert calls["count"] == ig_client.MAX_RETRIES + 1


def test_real_mode_parses_insights_response(real_mode, monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return FakeResponse(
            200,
            {"data": [{"name": "reach", "values": [{"value": 1234}]}, {"name": "saved", "values": [{"value": 5}]}]},
        )

    monkeypatch.setattr(ig_client.requests, "get", fake_get)

    client = IGClient()
    insights = client.get_media_insights("some-media-id")

    assert insights == {"reach": 1234, "saved": 5}
