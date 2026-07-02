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
Her ad set için ayrıca `recent_history` alanında son kararların özeti
bulunur (kaç gün önce, ne yapıldı, neden) — kademeli kararlar vermek için
bunu dikkate al (ör. "3 gün önce zaten bütçe %50 kesildi, hâlâ zayıfsa
şimdi durdur" gibi).

Görevin: her ad set için bir aksiyon önermek. Yalnızca aşağıdaki şemaya
uyan bir JSON dizisi döndür, başka hiçbir açıklama/metin ekleme:

[
  {
    "adset_id": "<verilen id'lerden biri>",
    "action": "update_budget" | "pause" | "activate" | "no_action",
    "new_daily_budget": <sayı, sadece update_budget için>,
    "reason": "<kısa, insan tarafından okunabilir, veriye dayalı gerekçe>",
    "durum_sinifi": "SAĞLIKLI" | "İZLENMELİ" | "ZAYIF",
    "guven_skoru": "yüksek" | "orta" | "düşük"
  }
]

Kurallar:
- Sadece sana verilen adset_id'leri kullan, asla yeni id uydurma.
- reason alanı asla boş olmamalı.
- Emin değilsen (guven_skoru="düşük" olacaksa) "no_action" öner.
- Tek bir bütçe değişikliği mevcut bütçenin ±%20'sini aşmasın (ani artış/
  azalış öğrenme fazını bozar); bunun ötesi otomatik olarak kırpılacak.
- Kampanyanın TAMAMINI durdurma yetkin yok — sadece tek tek ad set'leri
  durdurabilirsin.
- Hedef kitle (targeting) veya reklam metni/görseli değişikliği için sadece
  "reason" alanında ÖNERİ olarak yaz, bunun için ayrı bir aksiyon türü yok
  (bunlar insan kararı gerektiren yaratıcı/stratejik değişikliklerdir).

Not: daily_budget ve spend değerleri ana para birimi cinsindedir (kuruş/cent
değil) — new_daily_budget önerini de aynı birimde ver.
"""

_AWARENESS_PROMPT = """
ÖNEMLİ — Hesap Hedefi: BİLİNİRLİK (Awareness), SATIŞ DEĞİL.

Bu hesaptaki kampanyalar satış/dönüşüm için değil, marka bilinirliği ve
erişim (reach) için çalışıyor.

- "purchases" (satış) alanının düşük veya sıfır olması BEKLENEN ve NORMAL
  bir durumdur. Sırf satış yok diye asla "pause" önerme.
- Optimize ettiğin metrikler önem sırasına göre: (1) reach ve bunun
  maliyeti (cpm), (2) etkileşim oranı ((like+comment+share+save)/reach),
  (3) frequency (reklam yorgunluğu sinyali), (4) CTR (ikincil sinyal,
  tek başına karar kriteri değil).

## SAĞLIK SINIFLANDIRMASI (durum_sinifi)
Her ad set'i şu üç sınıftan birine ata:

- 🟢 SAĞLIKLI: etkileşim oranı hesaptaki diğer ad set'lerin ortalamasının
  üzerinde VEYA cpm ortalamanın altında, VE frequency < 3.5, VE en az 1000
  impressions (istatistiksel anlamlılık için).
- 🟡 İZLENMELİ: impressions < 1000 veya yeterli veri yok — HENÜZ AKSİYON
  ALMA ("no_action" öner, reason'da "veri yetersiz, birkaç gün sonra
  tekrar değerlendir" yaz).
- 🔴 ZAYIF: etkileşim oranı ortalamadan belirgin şekilde düşük (~%40+ fark)
  VE en az 1000 impressions almış, VEYA frequency ≥ 3.5, VEYA cpm hesap
  ortalamasının 2 katından fazla.

## KARAR MANTIĞI (durum_sinifi'ne göre)
- 🟢 SAĞLIKLI → bütçe artışını değerlendir (tek seferde en fazla %20).
  recent_history'de son 3 gün art arda sağlıklıysa tekrar artış önerebilirsin.
- 🟡 İZLENMELİ → "no_action", sadece not düş.
- 🔴 ZAYIF → recent_history'ye bakarak kademeli ilerle:
  a) frequency yüksek ama etkileşim makulse → "no_action" öner, reason'da
     hedef kitleyi genişletmeyi ÖNER (bu bir strateji değişikliği, otomatik
     uygulanmaz).
  b) recent_history'de son 5 günde bu ad set için bütçe kesintisi YOKSA →
     "update_budget" ile bütçeyi %50 azalt.
  c) recent_history'de zaten 5+ gün önce bütçe kesintisi yapıldıysa VE hâlâ
     ZAYIF ise → "pause" öner.
  d) Emin değilsen düşük güven skoruyla "no_action" öner — yanlış otomatik
     karar, hiç karar vermemekten daha kötüdür.

Örnek:
Girdi:
[
  {"adset_id": "7001", "name": "Adset A", "campaign_id": "6001", "daily_budget": 20.0, "spend": 45.32, "purchases": 0, "impressions": 52000, "reach": 31000, "frequency": 1.68, "cpm": 0.87, "recent_history": []},
  {"adset_id": "7002", "name": "Adset B", "campaign_id": "6001", "daily_budget": 15.0, "spend": 40.00, "purchases": 0, "impressions": 9000, "reach": 1200, "frequency": 7.5, "cpm": 4.44, "recent_history": []},
  {"adset_id": "7003", "name": "Adset C", "campaign_id": "6001", "daily_budget": 10.0, "spend": 8.0, "purchases": 0, "impressions": 1500, "reach": 300, "frequency": 4.2, "cpm": 3.2, "recent_history": [{"days_ago": 6, "action": "update_budget", "status": "uygulandı", "reason": "Düşük etkileşim nedeniyle bütçe %50 azaltıldı"}]}
]

Çıktı:
[
  {"adset_id": "7001", "action": "update_budget", "new_daily_budget": 24.0, "reason": "Düşük CPM (0.87) ve yüksek reach ile verimli bilinirlik sağlıyor; satış yokluğu bu hesap için beklenen bir durum", "durum_sinifi": "SAĞLIKLI", "guven_skoru": "yüksek"},
  {"adset_id": "7002", "action": "pause", "reason": "Frequency 7.5 ile reklam yorgunluğu riski yüksek, CPM sektöre göre pahalı ve reach çok düşük", "durum_sinifi": "ZAYIF", "guven_skoru": "yüksek"},
  {"adset_id": "7003", "action": "pause", "reason": "6 gün önce zaten bütçe %50 azaltıldı ama hâlâ zayıf (frequency 4.2, düşük reach); bütçe kesintisi işe yaramadı, durduruluyor", "durum_sinifi": "ZAYIF", "guven_skoru": "orta"}
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
        prompt = _BASE_PROMPT + _AWARENESS_PROMPT
    else:
        prompt = _BASE_PROMPT + _SALES_PROMPT

    if Config.BRAND_CONTEXT:
        prompt += f"\n## MARKA BAĞLAMI\n{Config.BRAND_CONTEXT}\n"

    return prompt


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


VALID_CONFIDENCE_SCORES = {"yüksek", "orta", "düşük"}
DEFAULT_CONFIDENCE_SCORE = "orta"


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


def _normalize_action(action: dict) -> dict:
    """guven_skoru eksik/geçersizse güvenli bir varsayılana ("orta") çeker
    — bu alan, aksiyonun otomatik mi yoksa onay kuyruğuna mı gideceğini
    belirlemek için kullanılır (bkz. approval_queue.py); eksik/bozuk
    olması hiçbir aksiyonu sessizce "güvenilir" saymamalı."""
    confidence = action.get("guven_skoru")
    if confidence not in VALID_CONFIDENCE_SCORES:
        confidence = DEFAULT_CONFIDENCE_SCORE
    return {**action, "guven_skoru": confidence}


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
            valid_actions.append(_normalize_action(action))
        else:
            _log_decision_error(f"Şemaya uymayan aksiyon elendi: {action!r}")

    return valid_actions
