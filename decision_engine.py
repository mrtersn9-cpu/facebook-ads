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
from llm_utils import strip_json_markdown_fence

logger = logging.getLogger(__name__)

DECISION_ERRORS_LOG = os.path.join("logs", "decision_errors.log")
ALLOWED_ACTIONS = {"update_budget", "pause", "activate", "no_action"}
MAX_ADSETS_PER_REQUEST = 200

_BASE_PROMPT = """Sen bir Meta Ads bütçe/durum optimizasyon asistanısın.
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

Not: daily_budget ve spend değerleri ana para birimi cinsindedir (kuruş/cent
değil) — new_daily_budget önerini de aynı birimde ver.
"""

_AWARENESS_PROMPT = """
ÖNEMLİ — Hesap Hedefi: BİLİNİRLİK (Awareness), SATIŞ DEĞİL.

Bu hesaptaki kampanyalar satış/dönüşüm için değil, marka bilinirliği ve
erişim (reach) için çalışıyor. Buna göre:

- "purchases" (satış) alanının düşük veya sıfır olması BEKLENEN ve NORMAL
  bir durumdur. Sırf satış yok diye asla "pause" önerme.
- Bir ad set'in başarısını şu bilinirlik metrikleriyle değerlendir:
  reach (kaç benzersiz kişiye ulaşıldı), impressions (gösterim), frequency
  (kişi başına ortalama gösterim — çok yüksekse (>4-5) reklam yorgunluğu
  riski var), cpm (1000 gösterim başına maliyet — düşük cpm daha verimli
  demektir).
- "pause" önerisini sadece şu gibi gerçek bilinirlik sorunlarında düşün:
  reach çok düşükken spend yüksekse, frequency aşırı yüksekse (reklam
  yorgunluğu), veya cpm sektöre göre anormal derecede yüksekse.
- "update_budget" önerisini reach/CPM verimliliği yüksek olan ad set'lere
  bütçe artışı, verimsiz (yüksek CPM, düşük reach) olanlara azaltma
  şeklinde kullan.

Örnek:
Girdi:
[
  {"adset_id": "7001", "name": "Adset A", "campaign_id": "6001", "daily_budget": 20.0, "spend": 45.32, "purchases": 0, "impressions": 52000, "reach": 31000, "frequency": 1.68, "cpm": 0.87},
  {"adset_id": "7002", "name": "Adset B", "campaign_id": "6001", "daily_budget": 15.0, "spend": 40.00, "purchases": 0, "impressions": 9000, "reach": 1200, "frequency": 7.5, "cpm": 4.44}
]

Çıktı:
[
  {"adset_id": "7001", "action": "update_budget", "new_daily_budget": 24.0, "reason": "Düşük CPM (0.87) ve yüksek reach ile verimli bilinirlik sağlıyor; satış yokluğu bu hesap için beklenen bir durum"},
  {"adset_id": "7002", "action": "pause", "reason": "Frequency 7.5 ile reklam yorgunluğu riski yüksek, CPM sektöre göre pahalı ve reach çok düşük"}
]
"""

_SALES_PROMPT = """
Hesap Hedefi: SATIŞ/DÖNÜŞÜM.

Örnek:
Girdi:
[
  {"adset_id": "7001", "name": "Adset A", "campaign_id": "6001", "daily_budget": 20.0, "spend": 45.32, "purchases": 3},
  {"adset_id": "7002", "name": "Adset B", "campaign_id": "6001", "daily_budget": 15.0, "spend": 12.10, "purchases": 0}
]

Çıktı:
[
  {"adset_id": "7001", "action": "update_budget", "new_daily_budget": 24.0, "reason": "Yüksek dönüşüm oranı ve pozitif ROAS; bütçe artışı fırsatı var"},
  {"adset_id": "7002", "action": "pause", "reason": "12 gündür harcama var ama hiç satış yok"}
]
"""


def _build_system_prompt() -> str:
    if Config.CAMPAIGN_OBJECTIVE == "awareness":
        return _BASE_PROMPT + _AWARENESS_PROMPT
    return _BASE_PROMPT + _SALES_PROMPT


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
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")

    try:
        actions = json.loads(strip_json_markdown_fence(text))
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
