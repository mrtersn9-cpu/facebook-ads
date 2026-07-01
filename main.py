"""Scheduler ve tek seferlik çalıştırma girişi.

Kullanım:
  python main.py --once     Boru hattını bir kez çalıştırıp çıkar.
  python main.py            RUN_INTERVAL_HOURS aralığıyla sürekli çalışır.
"""
import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
from data_fetcher import fetch_adset_performance
from decision_engine import get_action_recommendations
from guardrails import GuardrailViolation, apply_guardrails
from action_executor import execute_actions

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
from logger import log_action


def run_once() -> None:
    Config.validate()

    snapshot = fetch_adset_performance()
    if not snapshot:
        print("Aktif ad set bulunamadı veya veri yok; bu run'da yapılacak bir şey yok.")
        return

    actions = get_action_recommendations(snapshot)

    try:
        approved, rejected = apply_guardrails(actions, snapshot)
    except GuardrailViolation as exc:
        print(f"[GUARDRAIL IHLALI] {exc}")
        log_action(
            {
                "adset_id": None,
                "action": "run_blocked",
                "status": "guardrail_violation",
                "reason": str(exc),
            }
        )
        return

    for r in rejected:
        log_action(
            {
                "adset_id": r.get("adset_id"),
                "action": r.get("action"),
                "status": "rejected",
                "reason": r.get("rejection_reason"),
            }
        )

    summary = execute_actions(approved)

    print(
        "Çalıştırma özeti: "
        f"önerilen={len(actions)}, guardrail_red={len(rejected)}, "
        f"uygulanan={summary['applied']}, dry_run={summary['dry_run']}, "
        f"hata={summary['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta Ads AI Agent")
    parser.add_argument("--once", action="store_true", help="Boru hattını bir kez çalıştır ve çık.")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    scheduler = BlockingScheduler()
    scheduler.add_job(run_once, "interval", hours=Config.RUN_INTERVAL_HOURS)
    print(f"Scheduler başlatıldı: her {Config.RUN_INTERVAL_HOURS} saatte bir çalışacak.")
    scheduler.start()


if __name__ == "__main__":
    main()
