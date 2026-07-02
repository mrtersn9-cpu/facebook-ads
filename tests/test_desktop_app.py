"""desktop_app.py'nin log okuma mantığını doğrular. Gerçek bir Tkinter
penceresi açmaz (headless CI'da çalışabilir) — sadece pencere kurulumundan
bağımsız yardımcı fonksiyonu test eder."""
import json

from desktop_app import read_recent_log_entries


def _write_log(tmp_path, entries):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_returns_empty_list_when_no_log_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert read_recent_log_entries() == []


def test_returns_entries_most_recent_first(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_log(
        tmp_path,
        [
            {"timestamp": "1", "adset_id": "a"},
            {"timestamp": "2", "adset_id": "b"},
            {"timestamp": "3", "adset_id": "c"},
        ],
    )

    entries = read_recent_log_entries()

    assert [e["adset_id"] for e in entries] == ["c", "b", "a"]


def test_respects_limit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_log(tmp_path, [{"timestamp": str(i)} for i in range(10)])

    entries = read_recent_log_entries(limit=3)

    assert len(entries) == 3


def test_skips_malformed_lines(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    with open(log_dir / "actions.jsonl", "w", encoding="utf-8") as f:
        f.write("bozuk json\n")
        f.write(json.dumps({"timestamp": "1", "adset_id": "ok"}) + "\n")

    entries = read_recent_log_entries()

    assert len(entries) == 1
    assert entries[0]["adset_id"] == "ok"
