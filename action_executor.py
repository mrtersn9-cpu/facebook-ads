"""Guardrail'den geçmiş aksiyonları uygular (veya DRY_RUN modunda simüle eder).

Sadece guardrails.apply_guardrails()'ten onaylanmış aksiyonlar buraya
gelmelidir; bu modül kendi başına ek bir yetki kontrolü yapmaz.
"""
import signal

from config import Config
from logger import log_action
from meta_client import MetaClient, MetaAPIError

_shutdown_requested = False


def _handle_shutdown_signal(signum, frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def install_signal_handlers() -> None:
    """SIGINT/SIGTERM alındığında mevcut aksiyonun bitirilip yenisinin
    başlatılmamasını sağlayan bayrağı kurar. main.py girişinde bir kere
    çağrılmalı."""
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)


def execute_actions(actions: list[dict], client: MetaClient | None = None) -> dict:
    """Onaylanmış aksiyonları sırayla uygular; bir aksiyon hata verse bile
    diğerlerine devam eder. Her sonucu logs/actions.jsonl'e yazar.

    Bir kapatma sinyali (SIGINT/SIGTERM) alındığında mevcut aksiyon
    bitirilir ama yenisi başlatılmaz.

    Dönüş: {"applied": n, "dry_run": n, "errors": n, "no_action": n}
    """
    client = client or MetaClient()
    summary = {"applied": 0, "dry_run": 0, "errors": 0, "no_action": 0}

    for action in actions:
        if _shutdown_requested:
            log_action(
                {
                    "adset_id": None,
                    "action": "run_interrupted",
                    "status": "shutdown",
                    "reason": "Kapatma sinyali alındı; kalan aksiyonlar işlenmedi.",
                }
            )
            break

        adset_id = action.get("adset_id")
        action_type = action.get("action")
        reason = action.get("reason", "")

        if action_type == "no_action":
            log_action(
                {
                    "adset_id": adset_id,
                    "action": action_type,
                    "status": "no_action",
                    "reason": reason,
                }
            )
            summary["no_action"] += 1
            continue

        if Config.DRY_RUN:
            log_action(
                {
                    "adset_id": adset_id,
                    "action": action_type,
                    "status": "dry_run",
                    "reason": reason,
                    "details": action,
                }
            )
            summary["dry_run"] += 1
            continue

        try:
            if action_type == "update_budget":
                daily_budget_cents = int(round(float(action["new_daily_budget"]) * 100))
                client.update_adset_budget(adset_id, daily_budget_cents)
            elif action_type == "pause":
                client.pause_entity(adset_id)
            elif action_type == "activate":
                client.activate_entity(adset_id)

            log_action(
                {
                    "adset_id": adset_id,
                    "action": action_type,
                    "status": "applied",
                    "reason": reason,
                    "details": action,
                }
            )
            summary["applied"] += 1
        except MetaAPIError as exc:
            log_action(
                {
                    "adset_id": adset_id,
                    "action": action_type,
                    "status": "error",
                    "reason": reason,
                    "error": str(exc),
                }
            )
            summary["errors"] += 1

    return summary
