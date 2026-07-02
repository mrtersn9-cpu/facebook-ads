"""AUTOMATION_MODE="onayli" (varsayılan, güvenli) iken guardrail'den geçmiş
ama henüz uygulanmamış aksiyonları insan onayı bekleyen bir kuyrukta tutar.

Bu, DRY_RUN'dan bağımsız AYRI bir güvenlik katmanıdır: DRY_RUN gerçek API
çağrısı yapılıp yapılmayacağını kontrol eder, AUTOMATION_MODE ise
guardrail'den geçen bir aksiyonun hemen mi yoksa insan onayından sonra mı
işleneceğini kontrol eder. AUTOMATION_MODE="tam_otomatik" iken bu katman
tamamen atlanır ve aksiyonlar doğrudan action_executor'a gider (FAZ 0-12
davranışı).

Düşük hacimli bir kuyruk için basit dosya tabanlı depolama yeterlidir; her
işlemde tüm kuyruk okunup yazılır (DB gerektirmez).
"""
import json
import os
import uuid
from datetime import datetime, timezone

QUEUE_PATH = os.path.join("logs", "approval_queue.jsonl")


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(QUEUE_PATH) or ".", exist_ok=True)


def _read_all_entries() -> list[dict]:
    if not os.path.exists(QUEUE_PATH):
        return []
    entries = []
    with open(QUEUE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _write_all_entries(entries: list[dict]) -> None:
    _ensure_dir()
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def queue_action(action: dict) -> dict:
    """Guardrail'den geçmiş bir aksiyonu onay kuyruğuna ekler. Kuyruk
    kaydını döner (id dahil, arayüzde onayla/reddet butonları için)."""
    _ensure_dir()
    entry = {
        "id": uuid.uuid4().hex,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "action": action,
    }
    with open(QUEUE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_pending() -> list[dict]:
    """Henüz onaylanmamış/reddedilmemiş kayıtları en yeniden eskiye döner."""
    pending = [e for e in _read_all_entries() if e.get("status") == "pending"]
    pending.sort(key=lambda e: e.get("queued_at", ""), reverse=True)
    return pending


def resolve(entry_id: str, new_status: str) -> dict | None:
    """Bekleyen bir kaydı 'approved' veya 'rejected' olarak işaretler.
    Kayıt bulunamazsa veya zaten çözümlenmişse None döner."""
    if new_status not in ("approved", "rejected"):
        raise ValueError(f"Geçersiz durum: {new_status}")

    entries = _read_all_entries()
    resolved = None
    for entry in entries:
        if entry.get("id") == entry_id and entry.get("status") == "pending":
            entry["status"] = new_status
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            resolved = entry
            break

    if resolved:
        _write_all_entries(entries)
    return resolved
