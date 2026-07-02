"""run_creative_pipeline.py'nin manuel gönderi seçimi (media_ids) ile
otomatik top-N seçimi arasında doğru geçiş yaptığını doğrular. Gerçek
Meta/IG/Anthropic API'lerine hiç dokunmaz."""
import config
import run_creative_pipeline as pipeline

MEDIA = [
    {"id": "1", "like_count": 1, "comments_count": 0, "timestamp": "2020-01-01T00:00:00+0000"},
    {"id": "2", "like_count": 100, "comments_count": 0, "timestamp": "2020-01-01T00:00:00+0000"},
    {"id": "3", "like_count": 5, "comments_count": 0, "timestamp": "2020-01-01T00:00:00+0000"},
]


class FakeIGClient:
    def __init__(self, media):
        self._media = media

    def get_recent_media(self, ig_user_id):
        return self._media

    def get_media_insights(self, media_id):
        return {"reach": 100}


def _patch_common(monkeypatch, media=MEDIA):
    monkeypatch.setattr(config.Config, "KILL_SWITCH", False)
    monkeypatch.setattr(config.Config, "IG_MOCK_MODE", True)
    monkeypatch.setattr(pipeline, "IGClient", lambda: FakeIGClient(media))
    monkeypatch.setattr(pipeline.Config, "validate_ig", classmethod(lambda cls: None))

    captured = {}

    def fake_generate_creatives(posts):
        captured["posts"] = posts
        return []

    monkeypatch.setattr(pipeline, "generate_creatives", fake_generate_creatives)
    return captured


def test_explicit_media_ids_bypass_top_n_selection(monkeypatch, capsys):
    captured = _patch_common(monkeypatch)

    pipeline.run_once(media_ids=["1", "3"])

    processed_ids = {p["id"] for p in captured["posts"]}
    assert processed_ids == {"1", "3"}


def test_missing_media_ids_are_warned_and_skipped(monkeypatch, capsys):
    captured = _patch_common(monkeypatch)

    pipeline.run_once(media_ids=["1", "does-not-exist"])

    assert {p["id"] for p in captured["posts"]} == {"1"}
    assert "does-not-exist" in capsys.readouterr().out


def test_no_media_ids_uses_automatic_top_n_selection(monkeypatch):
    captured = _patch_common(monkeypatch)
    monkeypatch.setattr(config.Config, "IG_TOP_N_POSTS", 1)
    monkeypatch.setattr(config.Config, "IG_MIN_POST_AGE_HOURS", 0)
    monkeypatch.setattr(config.Config, "IG_ONLY_VIDEO_POSTS", False)

    pipeline.run_once(media_ids=None)

    assert [p["id"] for p in captured["posts"]] == ["2"]  # en yüksek like_count


def test_all_media_ids_missing_returns_early_without_generating(monkeypatch, capsys):
    captured = _patch_common(monkeypatch)

    pipeline.run_once(media_ids=["does-not-exist"])

    assert "posts" not in captured
    assert "bulunamadı" in capsys.readouterr().out.lower()


def test_kill_switch_skips_everything(monkeypatch):
    monkeypatch.setattr(config.Config, "KILL_SWITCH", True)

    def boom():
        raise AssertionError("KILL_SWITCH aktifken IGClient çağrılmamalı")

    monkeypatch.setattr(pipeline, "IGClient", boom)

    pipeline.run_once(media_ids=["1"])  # patlamamalı
