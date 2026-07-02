"""creative_guardrails.apply_creative_guardrails()'ten onaylanmış creative
önerilerini gerçek (ama her zaman PAUSED) kampanya -> ad set -> creative ->
reklam zincirine dönüştürür.

Bir zincirde hata olursa yarım kalan objeleri temizlemeye çalışmaz (silme
de riskli bir yazma işlemidir); bunun yerine hatayı ve o ana kadar oluşan
obje id'lerini açıkça loglar, insan manuel temizleyebilsin. Farklı
creative'lerin zincirleri birbirinden bağımsızdır: biri başarısız olsa bile
diğerleri işlenmeye devam eder.
"""
import logging

from config import Config
from logger import log_action
from meta_client import MetaClient, MetaAPIError

logger = logging.getLogger(__name__)

CAMPAIGN_ACTION_NAME = "create_campaign_from_creative"
DEFAULT_TARGETING = {"geo_locations": {"countries": ["TR"]}}

# Reklamlar harici bir web sitesine değil, Instagram Direct'e mesaj
# göndermeye yönlendirir. Meta'nın mesaj CTA'sı yine de bir hedef linki
# istiyor; Instagram Direct için bu, ig.me deep-link formatıdır
# (https://ig.me/m/<kullanıcı_adı>, Config.IG_USERNAME'den okunur).
ADSET_OPTIMIZATION_GOAL = "CONVERSATIONS"
ADSET_DESTINATION_TYPE = "INSTAGRAM_DIRECT"
CREATIVE_CALL_TO_ACTION = "INSTAGRAM_MESSAGE"


def build_campaign_from_creative(creative: dict, post: dict, client: MetaClient | None = None) -> dict:
    """Tek bir creative önerisinden PAUSED kampanya/ad set/creative/reklam
    zincirini oluşturur. Başarısızlıkta o ana kadar oluşan obje id'lerini
    loglayıp exception'ı yeniden fırlatır (çağıran diğer creative'lere
    devam edip etmeyeceğine karar verir).

    Not: hedefleme (targeting) burada bilinçli bir yer tutucudur —
    insan onayından önce Ads Manager'da mutlaka gözden geçirilmelidir.
    """
    client = client or MetaClient()
    created: dict = {"media_id": post.get("id")}
    label = creative["headline"][:60]

    try:
        campaign = client.create_campaign(name=f"[Auto] {label}"[:100], objective="OUTCOME_ENGAGEMENT")
        created["campaign_id"] = campaign["id"]

        adset = client.create_adset(
            campaign_id=campaign["id"],
            name=f"[Auto] {label} - Adset"[:100],
            daily_budget_cents=int(round(Config.DEFAULT_NEW_ADSET_DAILY_BUDGET * 100)),
            targeting=DEFAULT_TARGETING,
            optimization_goal=ADSET_OPTIMIZATION_GOAL,
            destination_type=ADSET_DESTINATION_TYPE,
        )
        created["adset_id"] = adset["id"]

        ad_creative = client.create_ad_creative(
            name=f"[Auto] {label} - Creative"[:100],
            instagram_media_id=post["id"],
            call_to_action_type=CREATIVE_CALL_TO_ACTION,
            call_to_action_link=f"https://ig.me/m/{Config.IG_USERNAME}" if Config.IG_USERNAME else None,
            instagram_actor_id=Config.IG_BUSINESS_ACCOUNT_ID or None,
        )
        created["creative_id"] = ad_creative["id"]

        ad = client.create_ad(adset_id=adset["id"], creative_id=ad_creative["id"], name=f"[Auto] {label} - Ad"[:100])
        created["ad_id"] = ad["id"]

        log_action(
            {
                "adset_id": adset["id"],
                "action": CAMPAIGN_ACTION_NAME,
                "status": "applied",
                "reason": creative.get("reasoning", ""),
                "details": created,
            }
        )
        return created

    except MetaAPIError as exc:
        logger.error(
            "Kampanya oluşturma zincirinde hata (media_id=%s): %s. O ana kadar oluşan objeler: %s",
            post.get("id"), exc, created,
        )
        log_action(
            {
                "adset_id": created.get("adset_id"),
                "action": CAMPAIGN_ACTION_NAME,
                "status": "error",
                "reason": str(exc),
                "details": created,
            }
        )
        raise


def build_campaigns_from_creatives(
    creatives: list[dict], posts_by_media_id: dict[str, dict], client: MetaClient | None = None
) -> dict:
    """Onaylanmış creative listesini sırayla işler; biri başarısız olsa bile
    diğerlerine devam eder. Dönüş: {"created": n, "errors": n, "results": [...]}
    """
    client = client or MetaClient()
    summary = {"created": 0, "errors": 0, "results": []}

    for creative in creatives:
        post = posts_by_media_id.get(creative["media_id"], {"id": creative["media_id"]})
        try:
            created = build_campaign_from_creative(creative, post, client=client)
            summary["created"] += 1
            summary["results"].append({"status": "created", **created})
        except MetaAPIError:
            summary["errors"] += 1
            summary["results"].append({"status": "error", "media_id": creative["media_id"]})

    return summary
