"""FAZ 12: campaign_builder.py'nin PAUSED-only zincir oluşturduğunu, kısmi
başarısızlıklarda temizlik denemeden loglayıp devam ettiğini doğrular.
Gerçek Meta API'ye hiç dokunmaz."""
import json

import pytest

import config
from campaign_builder import CampaignBuilderSkip, build_campaign_from_creative, build_campaigns_from_creatives
from meta_client import MetaAPIError

CREATIVE = {
    "media_id": "m1",
    "primary_text": "Yeni sezon başladı!",
    "headline": "Yeni Sezon",
    "description": "Şimdi keşfet.",
    "reasoning": "Yüksek engagement.",
}
POST = {"id": "m1"}


class FakeClient:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []

    def create_campaign(self, name, objective):
        self.calls.append("create_campaign")
        if self.fail_at == "create_campaign":
            raise MetaAPIError("campaign failed")
        return {"id": "camp_1", "status": "PAUSED"}

    def create_adset(self, campaign_id, name, daily_budget_cents, targeting, optimization_goal=None, destination_type=None):
        self.calls.append("create_adset")
        if self.fail_at == "create_adset":
            raise MetaAPIError("adset failed")
        return {"id": "adset_1", "status": "PAUSED"}

    def create_ad_creative(self, name, instagram_media_id=None, object_story_id=None, call_to_action_type=None, call_to_action_link=None):
        self.calls.append("create_ad_creative")
        if self.fail_at == "create_ad_creative":
            raise MetaAPIError("creative failed")
        return {"id": "creative_1"}

    def create_ad(self, adset_id, creative_id, name):
        self.calls.append("create_ad")
        if self.fail_at == "create_ad":
            raise MetaAPIError("ad failed")
        return {"id": "ad_1", "status": "PAUSED"}

    def find_page_post_id_for_timestamp(self, page_id, timestamp, tolerance_minutes=15):
        return getattr(self, "matched_post_id", None)


def test_full_chain_succeeds_and_logs_applied(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = FakeClient()

    result = build_campaign_from_creative(CREATIVE, POST, client=client)

    assert result == {
        "media_id": "m1",
        "campaign_id": "camp_1",
        "adset_id": "adset_1",
        "creative_id": "creative_1",
        "ad_id": "ad_1",
    }
    logged = json.loads((tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip())
    assert logged["status"] == "applied"
    assert logged["action"] == "create_campaign_from_creative"


def test_failure_midway_logs_partial_ids_and_reraises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = FakeClient(fail_at="create_ad_creative")

    try:
        build_campaign_from_creative(CREATIVE, POST, client=client)
        assert False, "MetaAPIError bekleniyordu"
    except MetaAPIError:
        pass

    assert client.calls == ["create_campaign", "create_adset", "create_ad_creative"]

    logged = json.loads((tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip())
    assert logged["status"] == "error"
    assert logged["details"]["campaign_id"] == "camp_1"
    assert logged["details"]["adset_id"] == "adset_1"
    assert "creative_id" not in logged["details"]
    assert "ad_id" not in logged["details"]


def test_batch_continues_after_one_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    calls = {"count": 0}

    class SequencedClient(FakeClient):
        def create_campaign(self, name, objective):
            calls["count"] += 1
            if calls["count"] == 2:
                raise MetaAPIError("second one fails")
            return {"id": f"camp_{calls['count']}", "status": "PAUSED"}

    client = SequencedClient()
    creatives = [{**CREATIVE, "media_id": f"m{i}"} for i in range(3)]
    posts_by_id = {f"m{i}": {"id": f"m{i}"} for i in range(3)}

    summary = build_campaigns_from_creatives(creatives, posts_by_id, client=client)

    assert summary["created"] == 2
    assert summary["errors"] == 1
    assert len(summary["results"]) == 3


class RecordingCreativeClient(FakeClient):
    def __init__(self, matched_post_id=None):
        super().__init__()
        self.matched_post_id = matched_post_id
        self.creative_calls = []

    def create_ad_creative(self, name, instagram_media_id=None, object_story_id=None, call_to_action_type=None, call_to_action_link=None):
        self.creative_calls.append(
            {"instagram_media_id": instagram_media_id, "object_story_id": object_story_id}
        )
        return super().create_ad_creative(name, instagram_media_id, object_story_id, call_to_action_type, call_to_action_link)

    def find_page_post_id_for_timestamp(self, page_id, timestamp, tolerance_minutes=15):
        return self.matched_post_id


def test_video_post_with_matching_page_post_uses_object_story_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "META_PAGE_ID", "page1")
    client = RecordingCreativeClient(matched_post_id="page1_12345")

    video_post = {"id": "m1", "media_type": "VIDEO", "timestamp": "2026-06-29T12:25:12+0000"}
    build_campaign_from_creative(CREATIVE, video_post, client=client)

    assert client.creative_calls == [{"instagram_media_id": None, "object_story_id": "page1_12345"}]


def test_video_post_without_match_is_skipped_without_any_api_call(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "META_PAGE_ID", "page1")
    client = RecordingCreativeClient(matched_post_id=None)

    video_post = {"id": "m1", "media_type": "VIDEO", "timestamp": "2026-06-29T12:25:12+0000"}

    with pytest.raises(CampaignBuilderSkip):
        build_campaign_from_creative(CREATIVE, video_post, client=client)

    # source_instagram_media_id ile video reklamı denemek güvenilir şekilde
    # başarısız olduğundan, hiçbir obje oluşturmaya çalışılmamalı.
    assert client.calls == []
    assert client.creative_calls == []

    logged = json.loads((tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip())
    assert logged["status"] == "skipped"


def test_image_post_always_uses_instagram_media_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "META_PAGE_ID", "page1")
    client = RecordingCreativeClient(matched_post_id="page1_should_not_be_used")

    image_post = {"id": "m1", "media_type": "IMAGE", "timestamp": "2026-06-29T12:25:12+0000"}
    build_campaign_from_creative(CREATIVE, image_post, client=client)

    assert client.creative_calls == [{"instagram_media_id": "m1", "object_story_id": None}]


def test_video_post_without_page_id_configured_is_skipped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "META_PAGE_ID", "")

    class ExplodingLookupClient(RecordingCreativeClient):
        def find_page_post_id_for_timestamp(self, page_id, timestamp, tolerance_minutes=15):
            raise AssertionError("META_PAGE_ID boşken lookup çağrılmamalı")

    client = ExplodingLookupClient()
    video_post = {"id": "m1", "media_type": "VIDEO", "timestamp": "2026-06-29T12:25:12+0000"}

    with pytest.raises(CampaignBuilderSkip):
        build_campaign_from_creative(CREATIVE, video_post, client=client)

    assert client.calls == []
    assert client.creative_calls == []


def test_skip_in_batch_is_counted_and_does_not_stop_other_creatives(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "META_PAGE_ID", "page1")

    client = RecordingCreativeClient(matched_post_id=None)
    creatives = [{**CREATIVE, "media_id": "video1"}, {**CREATIVE, "media_id": "image1"}]
    posts_by_id = {
        "video1": {"id": "video1", "media_type": "VIDEO", "timestamp": "2026-06-29T12:25:12+0000"},
        "image1": {"id": "image1", "media_type": "IMAGE"},
    }

    summary = build_campaigns_from_creatives(creatives, posts_by_id, client=client)

    assert summary["skipped"] == 1
    assert summary["created"] == 1
    assert summary["errors"] == 0
    assert {r["status"] for r in summary["results"]} == {"skipped", "created"}
