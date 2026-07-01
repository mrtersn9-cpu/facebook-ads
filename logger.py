"""Her aksiyonu insan tarafından okunabilir gerekçesiyle logs/actions.jsonl'e yazar.

FAZ 9: logs/actions.jsonl sonsuza kadar büyümesin diye boyut bazlı rotasyon
eklendi (actions.jsonl -> actions.jsonl.1 -> actions.jsonl.2 ...).
"""
import json
import os
from datetime import datetime, timezone

from config import Config

LOG_DIR = "logs"
ACTIONS_LOG_PATH = os.path.join(LOG_DIR, "actions.jsonl")
MAX_LOG_BYTES = Config.ACTIONS_LOG_MAX_BYTES
BACKUP_COUNT = Config.ACTIONS_LOG_BACKUP_COUNT


def _ensure_log_dir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def _rotate_if_needed() -> None:
    if not os.path.exists(ACTIONS_LOG_PATH):
        return
    if os.path.getsize(ACTIONS_LOG_PATH) < MAX_LOG_BYTES:
        return

    for i in range(BACKUP_COUNT - 1, 0, -1):
        src = f"{ACTIONS_LOG_PATH}.{i}"
        dst = f"{ACTIONS_LOG_PATH}.{i + 1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(ACTIONS_LOG_PATH, f"{ACTIONS_LOG_PATH}.1")


def log_action(entry: dict) -> None:
    """Bir aksiyon kaydını JSONL formatında ekler.

    entry en azından şunları içermeli: adset_id, action, status
    (ör. "applied", "dry_run", "rejected", "error"), reason.
    """
    _ensure_log_dir()
    _rotate_if_needed()
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with open(ACTIONS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
