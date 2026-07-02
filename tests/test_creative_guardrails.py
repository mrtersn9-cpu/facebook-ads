"""FAZ 12: creative_guardrails.py'nin fail-closed davrandığını kanıtlayan
testler. Tamamen izole — gerçek Meta API'ye hiç dokunmaz."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import config
from creative_guardrails import CreativeGuardrailViolation, apply_creative_guardrails

CREATIVE = {
    "media_id": "m1",
    "primary_text": "Yeni koleksiyonu keşfet, şimdi sipariş ver!",
    "headline": "Yeni Sezon",
    "description": "Kaçırma.",
    "reasoning": "Yüksek engagement.",
}


def _write_log(tmp_path, entries):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_banned_phrase_is_rejected_without_any_api_call(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 5)

    creative = {**CREATIVE, "primary_text": "Bu ürün garantili sonuç verir!"}

    approved, rejected = apply_creative_guardrails([creative])

    assert approved == []
    assert "Yasaklı ifade" in rejected[0]["rejection_reason"]


@pytest.mark.parametrize(
    "phrase",
    ["kesin kazan", "%100 başarı", "sınavı garanti", "üniversiteyi garantile", "başarısız olursan", "kaybetme riski"],
)
def test_education_sector_banned_phrase_is_rejected(monkeypatch, tmp_path, phrase):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 5)

    creative = {**CREATIVE, "headline": f"Bu kursla {phrase}!"}

    approved, rejected = apply_creative_guardrails([creative])

    assert approved == []
    assert "Yasaklı ifade" in rejected[0]["rejection_reason"]


def test_clean_creative_is_approved(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 5)

    approved, rejected = apply_creative_guardrails([CREATIVE])

    assert rejected == []
    assert approved == [CREATIVE]


def test_max_new_campaigns_per_run_truncates_excess(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 2)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 10)

    creatives = [{**CREATIVE, "media_id": f"m{i}"} for i in range(5)]

    approved, rejected = apply_creative_guardrails(creatives)

    assert len(approved) == 2
    assert len(rejected) == 3


def test_max_new_campaigns_per_day_blocks_everything_when_reached(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 2)

    now = datetime.now(timezone.utc)
    _write_log(
        tmp_path,
        [
            {"timestamp": now.isoformat(), "action": "create_campaign_from_creative", "status": "applied"},
            {"timestamp": now.isoformat(), "action": "create_campaign_from_creative", "status": "applied"},
        ],
    )

    with pytest.raises(CreativeGuardrailViolation):
        apply_creative_guardrails([CREATIVE])


def test_yesterdays_campaigns_do_not_count_toward_todays_limit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 2)

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    _write_log(
        tmp_path,
        [
            {"timestamp": yesterday.isoformat(), "action": "create_campaign_from_creative", "status": "applied"},
            {"timestamp": yesterday.isoformat(), "action": "create_campaign_from_creative", "status": "applied"},
        ],
    )

    approved, rejected = apply_creative_guardrails([CREATIVE])

    assert approved == [CREATIVE]


def test_rejected_or_error_status_entries_do_not_count(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 1)

    now = datetime.now(timezone.utc)
    _write_log(
        tmp_path,
        [
            {"timestamp": now.isoformat(), "action": "create_campaign_from_creative", "status": "error"},
            {"timestamp": now.isoformat(), "action": "some_other_action", "status": "applied"},
        ],
    )

    approved, rejected = apply_creative_guardrails([CREATIVE])

    assert approved == [CREATIVE]


def test_no_log_file_means_zero_campaigns_today(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 5)

    approved, rejected = apply_creative_guardrails([CREATIVE])

    assert approved == [CREATIVE]


def test_malformed_log_lines_are_skipped_without_crashing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_RUN", 5)
    monkeypatch.setattr(config.Config, "MAX_NEW_CAMPAIGNS_PER_DAY", 5)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        f.write("\n")  # boş satır
        f.write("bu gecerli bir json degil\n")  # bozuk JSON
        f.write(json.dumps({"action": "create_campaign_from_creative", "status": "applied"}) + "\n")  # timestamp yok

    approved, rejected = apply_creative_guardrails([CREATIVE])

    assert approved == [CREATIVE]  # hiçbiri sayılmadı, limit aşılmadı
