"""Ad set performans snapshot'ını Claude API'ye gönderip yapılandırılmış
JSON aksiyon önerileri üretir.

FAZ 2: bozuk/eksik cevaplar loglanır, şema doğrulama eklenir, büyük
snapshot'lar en yüksek harcamalı ilk N ad set'e kırpılır.
"""
import json
import logging
import os

import anthropic

from config import Config

logger = logging.getLogger(__name__)

DECISION_ERRORS_LOG = os.path.join("logs", "decision_errors.log")
ALLOWED_ACTIONS = {"update_budget", "pause", "activate", "no_action"}
MAX_ADSETS_PER_REQUEST = 200

SYSTEM_PROMPT = """Sen bir Meta Ads bütçe/durum optimizasyon asistanısın.
Sana ad set'lerin harcama ve performans verisini (JSON liste) vereceğim.

Görevin: her ad set için bir aksiyon önermek. Yalnızca aşağıdaki şemaya
uyan bir JSON dizisi döndür, başka hiçbir açıklama/metin ekleme:

[
  {
    "adset_id": "<verilen id'lerden biri>",
    "action": "update_budget" | "pause" | "activate" | "no_action",
    "new_daily_budget": <sayı, sadece update_budget için>,
    "reason": "<kısa, insan tarafından okunabilir gerekçe>"
  }
]

Kurallar:
- Sadece sana verilen adset_id'leri kullan, asla yeni id uydurma.
- reason alanı asla boş olmamalı.
- Emin değilsen "no_action" öner.

Örnek:
Girdi:
[
  {"adset_id": "7001", "name": "Adset A", "campaign_id": "6001", "daily_budget": "2000", "spend": 45.32, "purchases": 3},
  {"adset_id": "7002", "name": "Adset B", "campaign_id": "6001", "daily_budget": "1500", "spend": 12.10, "purchases": 0}
]

Çıktı:
[
  {"adset_id": "7001", "action": "update_budget", "new_daily_budget": 2400, "reason": "Yüksek dönüşüm oranı ve pozitif ROAS; bütçe artışı fırsatı var"},
  {"adset_id": "7002", "action": "pause", "reason": "12 gündür harcama var ama hiç satış yok"}
]
"""


def _log_decision_error(message: str) -> None:
    os.makedirs(os.path.dirname(DECISION_ERRORS_LOG) or ".", exist_ok=True)
    with open(DECISION_ERRORS_LOG, "a", encoding="utf-8") as f:
        f.write(message + "\n")
    logger.error(message)


def _prioritize_snapshot(snapshot: list[dict]) -> list[dict]:
    """Snapshot çok büyükse (ör. 200+ ad set) en yüksek harcamalı ilk N'i alır."""
    if len(snapshot) <= MAX_ADSETS_PER_REQUEST:
        return snapshot
    return sorted(snapshot, key=lambda row: row.get("spend", 0), reverse=True)[:MAX_ADSETS_PER_REQUEST]


def _validate_action(action) -> bool:
    if not isinstance(action, dict):
        return False
    if not action.get("adset_id"):
        return False
    if action.get("action") not in ALLOWED_ACTIONS:
        return False
    if not action.get("reason"):
        return False
    return True


def get_action_recommendations(snapshot: list[dict]) -> list[dict]:
    snapshot = _prioritize_snapshot(snapshot)

    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=Config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")

    try:
        actions = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        _log_decision_error(f"JSON parse hatası: {exc}. Ham cevap: {text[:1000]!r}")
        return []

    if not isinstance(actions, list):
        _log_decision_error(f"Beklenmeyen cevap tipi (liste değil): {type(actions).__name__}. Ham cevap: {text[:1000]!r}")
        return []

    valid_actions = []
    for action in actions:
        if _validate_action(action):
            valid_actions.append(action)
        else:
            _log_decision_error(f"Şemaya uymayan aksiyon elendi: {action!r}")

    return valid_actions
