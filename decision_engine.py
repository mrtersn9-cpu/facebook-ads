"""Ad set performans snapshot'ını Claude API'ye gönderip yapılandırılmış
JSON aksiyon önerileri üretir."""
import json

import anthropic

from config import Config

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
"""


def get_action_recommendations(snapshot: list[dict]) -> list[dict]:
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
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(actions, list):
        return []

    return actions
