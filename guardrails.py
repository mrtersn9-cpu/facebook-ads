"""Karar motorunun ürettiği aksiyonları kod-tabanlı güvenlik sınırlarından geçirir.

Guardrail katmanı asla bypass edilmez: decision_engine çıktısı burada
doğrulanıp/kırpılmadan action_executor'a gitmez.
"""
from config import Config

ALLOWED_ACTIONS = {"update_budget", "pause", "activate", "no_action"}


class GuardrailViolation(Exception):
    """Bir run'ın toplamda kabul edilemez bir riske yol açtığı durumda fırlatılır.

    Bu durumda o run için HİÇBİR aksiyon uygulanmaz (fail-closed).
    """


def _clamp_budget(current_budget: float, proposed_budget: float) -> float:
    max_change = current_budget * (Config.MAX_BUDGET_CHANGE_PERCENT / 100)
    lower = current_budget - max_change
    upper = current_budget + max_change
    return max(lower, min(upper, proposed_budget))


def apply_guardrails(actions: list[dict], snapshot: list[dict]) -> tuple[list[dict], list[dict]]:
    """Aksiyonları doğrular, kırpar ve onaylanan/reddedilen olarak ikiye ayırır.

    Dönüş: (approved, rejected). rejected elemanlarının her biri orijinal
    aksiyona ek olarak "rejection_reason" alanı içerir.

    Onaylanan update_budget aksiyonlarının toplamı MAX_DAILY_BUDGET_TOTAL'ı
    aşarsa GuardrailViolation fırlatılır; bu run için hiçbir aksiyon
    uygulanmamalıdır (fail-closed).
    """
    known = {row["adset_id"]: row for row in snapshot}

    approved: list[dict] = []
    rejected: list[dict] = []

    for action in actions[: Config.MAX_ACTIONS_PER_RUN]:
        adset_id = action.get("adset_id")
        action_type = action.get("action")
        reason = action.get("reason", "")

        if action_type not in ALLOWED_ACTIONS:
            rejected.append({**action, "rejection_reason": f"Bilinmeyen aksiyon: {action_type}"})
            continue

        if not reason:
            rejected.append({**action, "rejection_reason": "reason alanı boş"})
            continue

        if adset_id not in known:
            rejected.append(
                {**action, "rejection_reason": f"Bilinmeyen/uydurulmuş adset_id: {adset_id}"}
            )
            continue

        adset = known[adset_id]

        if action_type not in ("pause", "no_action"):
            if adset["spend"] < Config.MIN_SPEND_BEFORE_ACTION:
                rejected.append(
                    {
                        **action,
                        "rejection_reason": (
                            f"Minimum harcama eşiğinin altında "
                            f"(spend={adset['spend']}, min={Config.MIN_SPEND_BEFORE_ACTION})"
                        ),
                    }
                )
                continue

        if action_type == "update_budget":
            current_budget = float(adset.get("daily_budget") or 0)
            proposed = float(action.get("new_daily_budget", current_budget))
            clamped = _clamp_budget(current_budget, proposed) if current_budget > 0 else proposed
            action = {**action, "new_daily_budget": clamped}

        approved.append(action)

    total_budget = sum(a["new_daily_budget"] for a in approved if a["action"] == "update_budget")
    if total_budget > Config.MAX_DAILY_BUDGET_TOTAL:
        raise GuardrailViolation(
            f"Toplam önerilen günlük bütçe ({total_budget}) MAX_DAILY_BUDGET_TOTAL "
            f"({Config.MAX_DAILY_BUDGET_TOTAL}) sınırını aşıyor. Bu run'da hiçbir "
            f"aksiyon uygulanmayacak."
        )

    return approved, rejected
