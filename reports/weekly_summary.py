"""logs/actions.jsonl'i okuyup basit bir özet raporu üretir.

Kullanım: python reports/weekly_summary.py [gün_sayısı]
Varsayılan: son 7 gün.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

LOG_PATH = "logs/actions.jsonl"


def load_entries(since: datetime) -> list[dict]:
    entries = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= since:
                    entries.append(entry)
    except FileNotFoundError:
        pass
    return entries


def summarize(days: int = 7) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    entries = load_entries(since)

    status_counts = Counter(e.get("status") for e in entries)
    adset_counts = Counter(e.get("adset_id") for e in entries if e.get("adset_id"))

    lines = [f"Son {days} gün özeti ({len(entries)} kayıt):"]
    for status, count in status_counts.most_common():
        lines.append(f"  {status}: {count}")

    lines.append("En çok değiştirilen ad set'ler:")
    if not adset_counts:
        lines.append("  (kayıt yok)")
    for adset_id, count in adset_counts.most_common(5):
        lines.append(f"  {adset_id}: {count} aksiyon")

    return "\n".join(lines)


if __name__ == "__main__":
    days_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(summarize(days_arg))
