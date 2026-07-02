"""Slack webhook üzerinden opsiyonel bildirim gönderir.

SLACK_WEBHOOK_URL ayarlı değilse sessizce hiçbir şey yapmaz — bu zorunlu
bir bağımlılık değildir, sistem webhook olmadan da normal çalışmaya devam
etmelidir.
"""
import logging

import requests

from config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


def _send(text: str) -> None:
    if not Config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(Config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Slack bildirimi gönderilemedi: %s", exc)


def notify_run_summary(summary: dict, proposed_count: int, rejected_count: int) -> None:
    _send(
        "Meta Ads Agent çalıştırma özeti: "
        f"önerilen={proposed_count}, guardrail_red={rejected_count}, "
        f"uygulanan={summary['applied']}, dry_run={summary['dry_run']}, "
        f"no_action={summary.get('no_action', 0)}, hata={summary['errors']}"
    )


def notify_guardrail_violation(message: str) -> None:
    """Guardrail ihlali her zaman bildirilmelidir — bu dikkat gerektiren
    bir durumdur. Webhook ayarlı değilse yine de sessizce atlanır."""
    _send(f"⚠️ GUARDRAIL İHLALİ: {message}")


def notify_new_campaign_pending_review(campaign_id: str, ad_account_id: str) -> None:
    """FAZ 12: bot tarafından oluşturulan her yeni (PAUSED) kampanya için
    insan incelemesi bekleyen bir bildirim gönderir."""
    ads_manager_url = f"https://www.facebook.com/adsmanager/manage/campaigns?act={ad_account_id}"
    _send(
        f"🆕 İncelemeni bekleyen yeni (PAUSED) reklam kampanyası oluşturuldu: "
        f"{campaign_id}. Ads Manager: {ads_manager_url}"
    )
