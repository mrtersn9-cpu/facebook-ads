"""FAZ 9: logs/actions.jsonl'in sonsuza kadar büyümediğini, boyut aşılınca
rotate edildiğini doğrular."""
import json
from datetime import datetime, timedelta, timezone

import logger


def test_log_action_writes_a_jsonl_line(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    logger.log_action({"adset_id": "1", "action": "pause", "status": "applied", "reason": "test"})

    lines = (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["adset_id"] == "1"
    assert "timestamp" in record


def test_log_rotates_when_size_exceeded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logger, "MAX_LOG_BYTES", 10)
    monkeypatch.setattr(logger, "BACKUP_COUNT", 2)

    logger.log_action({"adset_id": "1", "action": "pause", "status": "applied", "reason": "ilk"})
    logger.log_action({"adset_id": "2", "action": "pause", "status": "applied", "reason": "ikinci"})

    log_dir = tmp_path / "logs"
    assert (log_dir / "actions.jsonl").exists()
    assert (log_dir / "actions.jsonl.1").exists()
    assert json.loads((log_dir / "actions.jsonl.1").read_text(encoding="utf-8").strip())["adset_id"] == "1"
    assert json.loads((log_dir / "actions.jsonl").read_text(encoding="utf-8").strip())["adset_id"] == "2"


def test_rotation_keeps_backup_count_bounded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logger, "MAX_LOG_BYTES", 10)
    monkeypatch.setattr(logger, "BACKUP_COUNT", 2)

    for i in range(5):
        logger.log_action({"adset_id": str(i), "action": "pause", "status": "applied", "reason": "x"})

    log_dir = tmp_path / "logs"
    rotated_files = sorted(p.name for p in log_dir.glob("actions.jsonl.*"))
    assert rotated_files == ["actions.jsonl.1", "actions.jsonl.2"]


def test_small_logs_are_never_rotated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    for i in range(20):
        logger.log_action({"adset_id": str(i), "action": "pause", "status": "applied", "reason": "x"})

    log_dir = tmp_path / "logs"
    assert not list(log_dir.glob("actions.jsonl.*"))
    assert len((log_dir / "actions.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 20


def _write_raw(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_get_recent_actions_filters_by_adset_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    _write_raw(
        tmp_path / "logs" / "actions.jsonl",
        [
            {"timestamp": now.isoformat(), "adset_id": "1", "action": "pause", "reason": "a"},
            {"timestamp": now.isoformat(), "adset_id": "2", "action": "pause", "reason": "b"},
        ],
    )

    result = logger.get_recent_actions_for_adset("1")

    assert len(result) == 1
    assert result[0]["adset_id"] == "1"


def test_get_recent_actions_excludes_entries_older_than_days(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)
    _write_raw(
        tmp_path / "logs" / "actions.jsonl",
        [
            {"timestamp": old.isoformat(), "adset_id": "1", "action": "pause", "reason": "eski"},
            {"timestamp": now.isoformat(), "adset_id": "1", "action": "pause", "reason": "yeni"},
        ],
    )

    result = logger.get_recent_actions_for_adset("1", days=10)

    assert len(result) == 1
    assert result[0]["reason"] == "yeni"


def test_get_recent_actions_reads_rotated_files_too(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    _write_raw(tmp_path / "logs" / "actions.jsonl", [{"timestamp": now.isoformat(), "adset_id": "1", "action": "pause", "reason": "current"}])
    _write_raw(tmp_path / "logs" / "actions.jsonl.1", [{"timestamp": now.isoformat(), "adset_id": "1", "action": "update_budget", "reason": "rotated"}])

    result = logger.get_recent_actions_for_adset("1")

    assert {r["reason"] for r in result} == {"current", "rotated"}


def test_get_recent_actions_sorted_newest_first_and_limited(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    entries = [
        {"timestamp": (now - timedelta(hours=i)).isoformat(), "adset_id": "1", "action": "pause", "reason": f"r{i}"}
        for i in range(10)
    ]
    _write_raw(tmp_path / "logs" / "actions.jsonl", entries)

    result = logger.get_recent_actions_for_adset("1", limit=3)

    assert [r["reason"] for r in result] == ["r0", "r1", "r2"]


def test_get_recent_actions_empty_when_no_logs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert logger.get_recent_actions_for_adset("1") == []
