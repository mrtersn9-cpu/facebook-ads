"""FAZ 11: creative_generator.py'nin bozuk/eksik Claude cevaplarını güvenle
ele aldığını ve organik caption'ı reklam metni olarak kullanmadığını
doğrular. Gerçek Anthropic API'ye hiç dokunmaz; gerçek Meta API'ye
hiçbir yazma çağrısı yapılmaz (bu modül sadece metin üretir)."""
import json

import creative_generator


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


class FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return FakeMessage(self._text)


class FakeAnthropicClient:
    def __init__(self, text):
        self.messages = FakeMessages(text)


def _patch_anthropic(monkeypatch, text):
    monkeypatch.setattr(creative_generator.anthropic, "Anthropic", lambda api_key: FakeAnthropicClient(text))


POST = {
    "id": "ig_media_1",
    "caption": "Yeni koleksiyonumuz mağazalarda!",
    "media_type": "IMAGE",
    "engagement_rate": 0.1,
    "like_count": 850,
    "comments_count": 42,
}


def test_valid_creative_is_returned(monkeypatch):
    payload = json.dumps(
        {
            "media_id": "ig_media_1",
            "primary_text": "Sınırlı süre! Yeni koleksiyonu şimdi keşfet.",
            "headline": "Yeni Sezon Burada",
            "description": "Hemen alışverişe başla.",
            "reasoning": "Yüksek engagement, güçlü CTA ile reklama uygun.",
        }
    )
    _patch_anthropic(monkeypatch, payload)

    creative = creative_generator.generate_creative_for_post(POST)

    assert creative["media_id"] == "ig_media_1"
    assert creative["primary_text"] != POST["caption"]


def test_broken_json_returns_none(monkeypatch):
    _patch_anthropic(monkeypatch, "bu json değil")

    assert creative_generator.generate_creative_for_post(POST) is None


def test_missing_field_returns_none(monkeypatch):
    payload = json.dumps(
        {
            "media_id": "ig_media_1",
            "primary_text": "metin",
            "headline": "başlık",
            # description eksik
            "reasoning": "gerekçe",
        }
    )
    _patch_anthropic(monkeypatch, payload)

    assert creative_generator.generate_creative_for_post(POST) is None


def test_mismatched_media_id_returns_none(monkeypatch):
    payload = json.dumps(
        {
            "media_id": "baska-bir-id",
            "primary_text": "metin",
            "headline": "başlık",
            "description": "açıklama",
            "reasoning": "gerekçe",
        }
    )
    _patch_anthropic(monkeypatch, payload)

    assert creative_generator.generate_creative_for_post(POST) is None


def test_identical_to_organic_caption_returns_none(monkeypatch):
    payload = json.dumps(
        {
            "media_id": "ig_media_1",
            "primary_text": POST["caption"],
            "headline": "başlık",
            "description": "açıklama",
            "reasoning": "gerekçe",
        }
    )
    _patch_anthropic(monkeypatch, payload)

    assert creative_generator.generate_creative_for_post(POST) is None


def test_generate_creatives_skips_failures_and_keeps_successes(monkeypatch):
    calls = {"count": 0}

    def fake_generate(post):
        calls["count"] += 1
        if post["id"] == "bad":
            return None
        return {"media_id": post["id"], "primary_text": "x", "headline": "y", "description": "z", "reasoning": "r"}

    monkeypatch.setattr(creative_generator, "generate_creative_for_post", fake_generate)

    posts = [{"id": "good-1"}, {"id": "bad"}, {"id": "good-2"}]
    results = creative_generator.generate_creatives(posts)

    assert calls["count"] == 3
    assert [r["media_id"] for r in results] == ["good-1", "good-2"]
