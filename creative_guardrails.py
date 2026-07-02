"""FAZ 11'in ürettiği creative önerilerini kampanya/ad set/reklam
oluşturmadan önce kod-tabanlı güvenlik sınırlarından geçirir.

guardrails.py'den kasıtlı olarak ayrıdır: bu katman farklı bir risk sınıfını
(sıfırdan yeni harcama başlatma) kapsar ve en az o kadar katıdır. Bir
ihlalde hiçbir obje oluşturulmaz (fail-closed).
"""
import json
import os
from datetime import datetime, timezone

from config import Config

ACTIONS_LOG_PATH = os.path.join("logs", "actions.jsonl")
CAMPAIGN_ACTION_NAME = "create_campaign_from_creative"

BANNED_PHRASES = [
    "garantili sonuç",
    "garantili",
    "kesin sonuç",
    "mucize",
    "%100 etkili",
    "tıbbi olarak kanıtlanmış",
    "hastalığı tedavi eder",
    "yan etkisi yok",
]


class CreativeGuardrailViolation(Exception):
    """Bir run'ın günlük kampanya oluşturma sınırını aştığı durumda
    fırlatılır. Bu durumda hiçbir yeni kampanya oluşturulmaz (fail-closed).
    """


def _contains_banned_phrase(text: str) -> str | None:
    lowered = (text or "").lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def _count_campaigns_created_today() -> int:
    """logs/actions.jsonl'den bugün (UTC) başarıyla oluşturulmuş kampanya
    sayısını sayar. Bozuk satırlar sessizce atlanır."""
    if not os.path.exists(ACTIONS_LOG_PATH):
        return 0

    today = datetime.now(timezone.utc).date()
    count = 0
    with open(ACTIONS_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("action") != CAMPAIGN_ACTION_NAME or entry.get("status") != "applied":
                continue

            try:
                entry_date = datetime.fromisoformat(entry["timestamp"]).date()
            except (KeyError, ValueError, TypeError):
                continue

            if entry_date == today:
                count += 1

    return count
def apply_creative_guardrails(creatives: list[dict]) -> tuple[list[dict], list[dict]]:
    """Creative önerilerini onaylanan/reddedilen olarak ikiye ayırır.

    - Yasaklı ifade içeren creative'ler reddedilir (rejection_reason ile).
    - Günlük ve run başına kampanya limitini aşan fazlalık, hataya değil
      sadece bu run'da işlenmeyecek şekilde reddedilir.
    - Bugün zaten MAX_NEW_CAMPAIGNS_PER_DAY'e ulaşılmışsa
      CreativeGuardrailViolation fırlatılır ve hiçbir creative onaylanmaz.
    """
    already_today = _count_campaigns_created_today()
    if already_today >= Config.MAX_NEW_CAMPAIGNS_PER_DAY:
        raise CreativeGuardrailViolation(
            f"Bugün zaten {already_today} kampanya oluşturuldu "
            f"(MAX_NEW_CAMPAIGNS_PER_DAY={Config.MAX_NEW_CAMPAIGNS_PER_DAY}). "
            "Bu run'da yeni kampanya oluşturulmayacak."
        )

    remaining_today = Config.MAX_NEW_CAMPAIGNS_PER_DAY - already_today
    run_limit = min(Config.MAX_NEW_CAMPAIGNS_PER_RUN, remaining_today)

    approved: list[dict] = []
    rejected: list[dict] = []

    for creative in creatives:
        banned = _contains_banned_phrase(creative.get("primary_text", "")) or _contains_banned_phrase(
            creative.get("headline", "")
        )
        if banned:
            rejected.append({**creative, "rejection_reason": f"Yasaklı ifade tespit edildi: '{banned}'"})
            continue

        if len(approved) >= run_limit:
            rejected.append(
                {
                    **creative,
                    "rejection_reason": (
                        "MAX_NEW_CAMPAIGNS_PER_RUN/MAX_NEW_CAMPAIGNS_PER_DAY sınırına ulaşıldı"
                    ),
                }
            )
            continue

        approved.append(creative)

    return approved, rejected
