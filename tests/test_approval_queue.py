"""approval_queue.py'nin bekleyen aksiyonları doğru kuyruklayıp
onaylayıp/reddedebildiğini doğrular."""
import json

import pytest

import approval_queue

ACTION = {"adset_id": "1", "action": "pause", "reason": "test"}


def test_queue_action_creates_pending_entry(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    entry = approval_queue.queue_action(ACTION)

    assert entry["status"] == "pending"
    assert entry["action"] == ACTION
    assert "id" in entry and "queued_at" in entry

    lines = (tmp_path / "logs" / "approval_queue.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == entry["id"]


def test_list_pending_returns_only_pending_entries(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    e1 = approval_queue.queue_action({**ACTION, "adset_id": "1"})
    approval_queue.queue_action({**ACTION, "adset_id": "2"})
    approval_queue.resolve(e1["id"], "approved")

    pending = approval_queue.list_pending()

    assert len(pending) == 1
    assert pending[0]["action"]["adset_id"] == "2"


def test_list_pending_empty_when_no_queue_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert approval_queue.list_pending() == []


def test_resolve_approves_entry(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    entry = approval_queue.queue_action(ACTION)

    resolved = approval_queue.resolve(entry["id"], "approved")

    assert resolved["status"] == "approved"
    assert "resolved_at" in resolved
    assert approval_queue.list_pending() == []


def test_resolve_rejects_entry(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    entry = approval_queue.queue_action(ACTION)

    resolved = approval_queue.resolve(entry["id"], "rejected")

    assert resolved["status"] == "rejected"


def test_resolve_unknown_id_returns_none(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    approval_queue.queue_action(ACTION)

    assert approval_queue.resolve("does-not-exist", "approved") is None


def test_resolve_already_resolved_entry_returns_none(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    entry = approval_queue.queue_action(ACTION)
    approval_queue.resolve(entry["id"], "approved")

    assert approval_queue.resolve(entry["id"], "rejected") is None


def test_resolve_rejects_invalid_status(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    entry = approval_queue.queue_action(ACTION)

    with pytest.raises(ValueError):
        approval_queue.resolve(entry["id"], "maybe")


def test_multiple_pending_sorted_newest_first(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    approval_queue.queue_action({**ACTION, "adset_id": "1"})
    approval_queue.queue_action({**ACTION, "adset_id": "2"})

    pending = approval_queue.list_pending()

    assert [p["action"]["adset_id"] for p in pending] == ["2", "1"]
