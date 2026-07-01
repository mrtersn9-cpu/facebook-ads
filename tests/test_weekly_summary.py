"""FAZ 6: reports/weekly_summary.py'nin logs/actions.jsonl'i doğru
özetlediğini doğrular."""
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reports"))
import weekly_summary  # noqa: E402


def _write_log(tmp_path, entries):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_summarize_counts_statuses_and_top_adsets(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    importlib.reload(weekly_summary)

    now = datetime.now(timezone.utc)
    entries = [
        {"timestamp": now.isoformat(), "adset_id": "1", "status": "applied"},
        {"timestamp": now.isoformat(), "adset_id": "1", "status": "applied"},
        {"timestamp": now.isoformat(), "adset_id": "2", "status": "rejected"},
        {"timestamp": (now - timedelta(days=30)).isoformat(), "adset_id": "3", "status": "applied"},
    ]
    _write_log(tmp_path, entries)

    output = weekly_summary.summarize(days=7)

    assert "applied: 2" in output
    assert "rejected: 1" in output
    assert "1: 2 aksiyon" in output
    assert "3" not in output.split("En çok")[1]  # 30 gün önceki kayıt hariç


def test_summarize_handles_missing_log_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    importlib.reload(weekly_summary)

    output = weekly_summary.summarize(days=7)

    assert "0 kayıt" in output
