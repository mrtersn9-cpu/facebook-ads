"""FAZ 9: logs/actions.jsonl'in sonsuza kadar büyümediğini, boyut aşılınca
rotate edildiğini doğrular."""
import json

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
