"""FAZ 2: decision_engine.py'nin bozuk/eksik/şemaya uymayan Claude
cevaplarını güvenli şekilde ele aldığını doğrular. Gerçek Anthropic API'ye
hiç dokunmaz; anthropic.Anthropic monkeypatch ile sahtelenir."""
import json

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
