"""Aktif ad set'lerin performans verisini toplayıp karar motoru için bir
snapshot (özet liste) üretir."""
import logging

from config import Config
from meta_client import MetaClient

logger = logging.getLogger(__name__)


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
            }
        )

    return snapshot
