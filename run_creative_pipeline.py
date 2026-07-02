"""Instagram gönderilerinden reklam creative'i ve (her zaman PAUSED)
kampanya oluşturan, ayrı ve isteğe bağlı bir komut.

Bilinçli olarak `main.py`'nin bütçe optimizasyon döngüsünden AYRIDIR ve
onunla aynı process'te otomatik tetiklenmez — bu, sıfırdan yeni harcama
başlatan daha yüksek riskli bir işlem sınıfıdır ve insan bunu bilerek
çalıştırmalıdır (bkz. CLAUDE.md Değişmez Kural #8).

Kullanım:
  python run_creative_pipeline.py --once
"""
import argparse
import logging
import sys

from config import Config
from ig_client import IGClient
from post_selector import select_top_posts
from creative_generator import generate_creatives
from creative_guardrails import CreativeGuardrailViolation, apply_creative_guardrails
from campaign_builder import build_campaigns_from_creatives
from logger import log_action
from notifier import notify_guardrail_violation, notify_new_campaign_pending_review

# Windows konsolları varsayılan olarak UTF-8 kullanmayabilir; bu, Türkçe
# karakterlerin bozuk görünmesine yol açar.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_once() -> None:
    logger.info("heartbeat: creative pipeline run_once başlıyor")

    if Config.KILL_SWITCH:
        print("KILL_SWITCH aktif; hiçbir dış çağrı yapılmadan çıkılıyor.")
        return

    Config.validate_ig()

    client = IGClient()
    media = client.get_recent_media(Config.IG_BUSINESS_ACCOUNT_ID)
    if not media:
        print("Hiç gönderi bulunamadı; bu run'da yapılacak bir şey yok.")
        return

    insights_by_id = {m["id"]: client.get_media_insights(m["id"]) for m in media}
    top_posts = select_top_posts(media, insights_by_id)
    if not top_posts:
        print("Reklam adayı olabilecek yeterince olgun/performanslı gönderi yok.")
        return

    creatives = generate_creatives(top_posts)
    if not creatives:
        print("Hiçbir geçerli creative üretilemedi (bkz. logs/decision_errors.log).")
        return

    try:
        approved, rejected = apply_creative_guardrails(creatives)
    except CreativeGuardrailViolation as exc:
        print(f"[CREATIVE GUARDRAIL IHLALI] {exc}")
        log_action(
            {
                "adset_id": None,
                "action": "creative_run_blocked",
                "status": "guardrail_violation",
                "reason": str(exc),
            }
        )
        notify_guardrail_violation(str(exc))
        return

    for r in rejected:
        log_action(
            {
                "adset_id": None,
                "action": "create_campaign_from_creative",
                "status": "rejected",
                "reason": r.get("rejection_reason"),
                "details": {"media_id": r.get("media_id")},
            }
        )

    posts_by_media_id = {p["id"]: p for p in top_posts}
    summary = build_campaigns_from_creatives(approved, posts_by_media_id)

    for result in summary["results"]:
        if result.get("status") == "created":
            notify_new_campaign_pending_review(result["campaign_id"], Config.META_AD_ACCOUNT_ID)

    print(
        "Creative pipeline özeti: "
        f"aday_gönderi={len(top_posts)}, üretilen_creative={len(creatives)}, "
        f"guardrail_red={len(rejected)}, oluşturulan={summary['created']}, "
        f"hata={summary['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram Creative Pipeline (FAZ 11-12)")
    parser.add_argument(
        "--once", action="store_true", required=True,
        help="Boru hattını bir kez çalıştır ve çık (tek desteklenen mod).",
    )
    parser.parse_args()

    run_once()


if __name__ == "__main__":
    main()
