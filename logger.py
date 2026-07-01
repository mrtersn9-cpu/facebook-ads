"""Her aksiyonu insan tarafından okunabilir gerekçesiyle logs/actions.jsonl'e yazar."""
import json
import os
from datetime import datetime, timezone

LOG_DIR = "logs"
ACTIONS_LOG_PATH = os.path.join(LOG_DIR, "actions.jsonl")


def _ensure_log_dir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def log_action(entry: dict) -> None:
    """Bir aksiyon kaydını JSONL formatında ekler.

    entry en azından şunları içermeli: adset_id, action, status
    (ör. "applied", "dry_run", "rejected", "error"), reason.
    """
    _ensure_log_dir()
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with open(ACTIONS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
