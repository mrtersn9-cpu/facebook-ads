"""Aktif ad set'lerin performans verisini toplayıp karar motoru için bir
snapshot (özet liste) üretir."""
import logging
from datetime import datetime, timezone

from config import Config
from logger import get_recent_actions_for_adset
from meta_client import MetaClient

logger = logging.getLogger(__name__)

HISTORY_LOOKBACK_DAYS = 10
HISTORY_LIMIT_PER_ADSET = 3
STATUS_LABELS = {
    "applied": "uygulandı",
    "dry_run": "simüle edildi (dry_run)",
    "queued_for_approval": "onaya gönderildi",
    "approved": "onaylanıp uygulandı",
    "rejected": "insan tarafından reddedildi",
}


def _summarize_history(adset_id: str) -> list[dict]:
    """Karar motoruna "hafıza" sağlamak için bu ad set'e ait son kararları
    kısa bir özet olarak döner (kaç gün önce, ne yapıldı, neden)."""
    now = datetime.now(timezone.utc)
    entries = get_recent_actions_for_adset(adset_id, days=HISTORY_LOOKBACK_DAYS, limit=HISTORY_LIMIT_PER_ADSET)

    summary = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (KeyError, ValueError):
            continue
        days_ago = round((now - ts).total_seconds() / 86400, 1)
        status = entry.get("status", "")
        summary.append(
            {
                "days_ago": days_ago,
                "action": entry.get("action"),
                "status": STATUS_LABELS.get(status, status),
                "reason": entry.get("reason", ""),
            }
        )
    return summary


def _extract_purchases(actions: list[dict]) -> int:
    for action in actions or []:
        if action.get("action_type") == "purchase":
            return int(float(action.get("value", 0)))
    return 0


def _resolve_scope_campaign_ids(client: MetaClient) -> set | None:
    """SCOPE_CAMPAIGN_NAME_FILTER ayarlıysa, adında bu alt dizeyi içeren
    kampanyaların id'lerini döner. Ayarlı değilse None (kapsam sınırı yok)."""
    if not Config.SCOPE_CAMPAIGN_NAME_FILTER:
        return None

    needle = Config.SCOPE_CAMPAIGN_NAME_FILTER.lower()
    matched = {c["id"] for c in client.get_campaigns() if needle in c.get("name", "").lower()}
    logger.info(
        "Kapsam filtresi aktif ('%s'): %d kampanya eşleşti.",
        Config.SCOPE_CAMPAIGN_NAME_FILTER, len(matched),
    )
    return matched


def fetch_adset_performance(client: MetaClient | None = None) -> list[dict]:
    """Aktif (ACTIVE) ad set'ler için harcama/performans snapshot'ı döner.

    SCOPE_CAMPAIGN_NAME_FILTER ayarlıysa sadece o kampanyalardaki ad set'ler
    dahil edilir (kademeli canlıya alma sırasında botun etkisini sınırlamak
    için — bkz. FAZ 8).

    Her eleman: adset_id, name, campaign_id, daily_budget, spend, purchases.
    """
    client = client or MetaClient()
    snapshot = []

    scope_campaign_ids = _resolve_scope_campaign_ids(client)

    for adset in client.get_adsets():
        if scope_campaign_ids is not None and adset.get("campaign_id") not in scope_campaign_ids:
            continue

        if adset.get("status") != "ACTIVE":
            continue

        insights = client.get_insights(adset["id"])
        if not insights:
            logger.debug(
                "Ad set %s (%s) için insight verisi yok, snapshot'a alınmıyor.",
                adset.get("id"), adset.get("name", ""),
            )
            continue

        row = insights[0]
        spend = float(row.get("spend", 0) or 0)

        if spend == 0:
            logger.debug(
                "Ad set %s (%s) sıfır harcamalı, snapshot'a alınmıyor.",
                adset.get("id"), adset.get("name", ""),
            )
            continue

        purchases = _extract_purchases(row.get("actions", []))

        # Graph API daily_budget'ı en küçük para birimi (kuruş/cent) cinsinden
        # döner; guardrails/decision_engine/action_executor tutarlılığı için
        # burada ana para birimine (ör. TL/USD) çeviriyoruz.
        raw_budget = adset.get("daily_budget")
        daily_budget = float(raw_budget) / 100 if raw_budget not in (None, "") else None

        snapshot.append(
            {
                "adset_id": adset["id"],
                "name": adset.get("name", ""),
                "campaign_id": adset.get("campaign_id", ""),
                "daily_budget": daily_budget,
                "spend": spend,
                "purchases": purchases,
                # Bilinirlik (awareness) odaklı hesaplar için: satın alma
                # olmasa da bu metrikler ad set'in gerçekten iş görüp
                # görmediğini gösterir.
                "impressions": int(float(row.get("impressions", 0) or 0)),
                "reach": int(float(row.get("reach", 0) or 0)),
                "frequency": float(row.get("frequency", 0) or 0),
                "cpm": float(row.get("cpm", 0) or 0),
                # Karar motorunun kademeli kararlar verebilmesi için (ör.
                # "3 gün önce zaten %50 kesildi, hâlâ zayıfsa şimdi durdur").
                "recent_history": _summarize_history(adset["id"]),
            }
        )

    return snapshot
