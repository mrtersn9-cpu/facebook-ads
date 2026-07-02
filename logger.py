"""Her aksiyonu insan tarafından okunabilir gerekçesiyle logs/actions.jsonl'e yazar.

FAZ 9: logs/actions.jsonl sonsuza kadar büyümesin diye boyut bazlı rotasyon
eklendi (actions.jsonl -> actions.jsonl.1 -> actions.jsonl.2 ...).
"""
import json
import os
from datetime import datetime, timedelta, timezone

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


def get_recent_actions_for_adset(adset_id: str, days: int = 10, limit: int = 5) -> list[dict]:
    """Bu ad set için son `days` gün içindeki (rotasyon dosyaları dahil)
    aksiyon kayıtlarını en yeniden eskiye sıralı döner. Karar motoruna
    "hafıza" sağlamak için kullanılır — ör. "bu ad set 3 gün önce zaten
    %50 bütçe kesintisi aldı, hâlâ zayıfsa şimdi durdur" gibi kademeli
    kararlar verebilmesi için.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    paths = [ACTIONS_LOG_PATH] + [f"{ACTIONS_LOG_PATH}.{i}" for i in range(1, BACKUP_COUNT + 1)]

    matches = []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("adset_id") != adset_id:
                    continue
                try:
                    ts = datetime.fromisoformat(entry["timestamp"])
                except (KeyError, ValueError):
                    continue
                if ts >= cutoff:
                    matches.append(entry)

    matches.sort(key=lambda e: e["timestamp"], reverse=True)
    return matches[:limit]
