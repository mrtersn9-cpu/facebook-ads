"""FAZ 6: notifier.py'nin opsiyonel bağımlılık davranışını doğrular."""
import config
import notifier


def test_no_webhook_configured_never_calls_requests(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "")

    def boom(*a, **k):
        raise AssertionError("Webhook ayarlı değilken requests.post çağrılmamalı")

    monkeypatch.setattr(notifier.requests, "post", boom)

    notifier.notify_run_summary({"applied": 1, "dry_run": 0, "errors": 0}, 1, 0)
    notifier.notify_guardrail_violation("test ihlali")


def test_webhook_configured_sends_run_summary(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/fake")
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    notifier.notify_run_summary({"applied": 2, "dry_run": 1, "errors": 0}, 3, 1)

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://hooks.slack.test/fake"
    assert "uygulanan=2" in payload["text"]


def test_webhook_configured_sends_guardrail_violation(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/fake")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda url, json=None, timeout=None: calls.append(json))

    notifier.notify_guardrail_violation("toplam bütçe aşıldı")

    assert len(calls) == 1
    assert "GUARDRAIL" in calls[0]["text"]
    assert "toplam bütçe aşıldı" in calls[0]["text"]


def test_request_exception_is_swallowed(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/fake")

    def raise_error(*a, **k):
        raise notifier.requests.RequestException("network down")

    monkeypatch.setattr(notifier.requests, "post", raise_error)

    notifier.notify_run_summary({"applied": 0, "dry_run": 0, "errors": 0}, 0, 0)  # patlamamalı


def test_new_campaign_pending_review_includes_ads_manager_link(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/fake")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda url, json=None, timeout=None: calls.append(json))

    notifier.notify_new_campaign_pending_review("camp_123", "999888777")

    assert len(calls) == 1
    assert "camp_123" in calls[0]["text"]
    assert "act=999888777" in calls[0]["text"]


def test_notify_queued_for_approval_sends_summary(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/fake")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda url, json=None, timeout=None: calls.append(json))

    notifier.notify_queued_for_approval(3, 5, 1)

    assert len(calls) == 1
    assert "onaya_gönderilen=3" in calls[0]["text"]
    assert "önerilen=5" in calls[0]["text"]
    assert "guardrail_red=1" in calls[0]["text"]


def test_notify_queued_for_approval_noop_without_webhook(monkeypatch):
    monkeypatch.setattr(config.Config, "SLACK_WEBHOOK_URL", "")

    def boom(*a, **k):
        raise AssertionError("Webhook ayarlı değilken requests.post çağrılmamalı")

    monkeypatch.setattr(notifier.requests, "post", boom)

    notifier.notify_queued_for_approval(1, 1, 0)  # patlamamalı
