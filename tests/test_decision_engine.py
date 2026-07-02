"""FAZ 2: decision_engine.py'nin bozuk/eksik/şemaya uymayan Claude
cevaplarını güvenli şekilde ele aldığını doğrular. Gerçek Anthropic API'ye
hiç dokunmaz; anthropic.Anthropic monkeypatch ile sahtelenir."""
import json

import config
import decision_engine


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
    monkeypatch.setattr(decision_engine.anthropic, "Anthropic", lambda api_key: FakeAnthropicClient(text))


def test_broken_json_returns_empty_list_and_logs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_anthropic(monkeypatch, "bu json değil, düz metin")

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions == []
    assert (tmp_path / "logs" / "decision_errors.log").exists()


def test_markdown_fenced_json_is_parsed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps([{"adset_id": "1", "action": "pause", "reason": "test"}])
    _patch_anthropic(monkeypatch, f"```json\n{payload}\n```")

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert len(actions) == 1
    assert actions[0]["adset_id"] == "1"


def test_non_list_json_returns_empty_list(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_anthropic(monkeypatch, json.dumps({"not": "a list"}))

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions == []


def test_missing_required_fields_are_dropped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps(
        [
            {"adset_id": "1", "action": "pause", "reason": "kötü performans"},
            {"adset_id": "2", "action": "pause"},
            {"action": "pause", "reason": "adset_id eksik"},
        ]
    )
    _patch_anthropic(monkeypatch, payload)

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert len(actions) == 1
    assert actions[0]["adset_id"] == "1"


def test_disallowed_action_type_is_dropped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps([{"adset_id": "1", "action": "delete_campaign", "reason": "..."}])
    _patch_anthropic(monkeypatch, payload)

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions == []


def test_large_snapshot_truncated_to_highest_spend(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class CapturingMessages:
        def create(self, **kwargs):
            captured["content"] = kwargs["messages"][0]["content"]
            return FakeMessage("[]")

    class CapturingClient:
        def __init__(self, api_key):
            self.messages = CapturingMessages()

    monkeypatch.setattr(decision_engine.anthropic, "Anthropic", CapturingClient)

    big_snapshot = [{"adset_id": str(i), "spend": i} for i in range(250)]
    decision_engine.get_action_recommendations(big_snapshot)

    sent = json.loads(captured["content"])
    assert len(sent) == decision_engine.MAX_ADSETS_PER_REQUEST
    assert sent[0]["spend"] == 249


def test_awareness_objective_prompt_tells_model_to_ignore_purchases(monkeypatch):
    monkeypatch.setattr(config.Config, "CAMPAIGN_OBJECTIVE", "awareness")

    prompt = decision_engine._build_system_prompt()

    assert "BİLİNİRLİK" in prompt
    assert "reach" in prompt
    assert "asla" in prompt.lower() and "pause" in prompt.lower()


def test_sales_objective_prompt_is_used_when_configured(monkeypatch):
    monkeypatch.setattr(config.Config, "CAMPAIGN_OBJECTIVE", "sales")

    prompt = decision_engine._build_system_prompt()

    assert "SATIŞ/DÖNÜŞÜM" in prompt
    assert "BİLİNİRLİK" not in prompt


def test_awareness_is_the_default_objective(monkeypatch):
    monkeypatch.setattr(config.Config, "CAMPAIGN_OBJECTIVE", "awareness")

    captured = {}

    class CapturingMessages:
        def create(self, **kwargs):
            captured["system"] = kwargs["system"]
            return FakeMessage("[]")

    class CapturingClient:
        def __init__(self, api_key):
            self.messages = CapturingMessages()

    monkeypatch.setattr(decision_engine.anthropic, "Anthropic", CapturingClient)

    decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert "BİLİNİRLİK" in captured["system"]


def test_brand_context_is_appended_when_set(monkeypatch):
    monkeypatch.setattr(config.Config, "BRAND_CONTEXT", "Sonuç Yayınları: YKS/TYT-AYT eğitim yayınevi.")

    prompt = decision_engine._build_system_prompt()

    assert "Sonuç Yayınları" in prompt
    assert "MARKA BAĞLAMI" in prompt


def test_brand_context_omitted_when_empty(monkeypatch):
    monkeypatch.setattr(config.Config, "BRAND_CONTEXT", "")

    prompt = decision_engine._build_system_prompt()

    assert "MARKA BAĞLAMI" not in prompt


def test_confidence_score_defaults_to_orta_when_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps([{"adset_id": "1", "action": "pause", "reason": "test"}])
    _patch_anthropic(monkeypatch, payload)

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions[0]["guven_skoru"] == "orta"


def test_confidence_score_defaults_to_orta_when_invalid(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps([{"adset_id": "1", "action": "pause", "reason": "test", "guven_skoru": "bilinmeyen"}])
    _patch_anthropic(monkeypatch, payload)

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions[0]["guven_skoru"] == "orta"


def test_confidence_score_preserved_when_valid(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps([{"adset_id": "1", "action": "pause", "reason": "test", "guven_skoru": "düşük"}])
    _patch_anthropic(monkeypatch, payload)

    actions = decision_engine.get_action_recommendations([{"adset_id": "1", "spend": 10}])

    assert actions[0]["guven_skoru"] == "düşük"
