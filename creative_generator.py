"""Seçilen organik Instagram gönderilerinden Claude ile reklam creative
metni (primary text, headline, description) üretir.

Organik caption asla olduğu gibi reklam metni olarak kullanılmaz — ton ve
CTA reklam formatına göre farklı olmalıdır. Bozuk/eksik Claude cevabında
hiçbir alan tahmin edilerek doldurulmaz; o gönderi için None dönülür.
"""
import json
import logging

import anthropic

from config import Config

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("media_id", "primary_text", "headline", "description", "reasoning")

SYSTEM_PROMPT = """Sen bir Meta Ads reklam metni yazarısın.
Sana organik bir Instagram gönderisinin caption'ını ve performans verisini
vereceğim. Görevin bu gönderiden ilham alan, ama organik caption'ın birebir
kopyası OLMAYAN, reklam formatına uygun yeni bir metin üretmek.

Kurallar:
- Organik caption'ı olduğu gibi kopyalama; ton ve CTA reklam formatına göre
  farklı olmalı (daha net bir eylem çağrısı, reklam bağlamına uygun dil).
- Sağlık iddiası, "garantili sonuç" gibi ifadeler kullanma.
- Sadece aşağıdaki şemaya uyan TEK bir JSON objesi döndür, başka hiçbir
  açıklama/metin ekleme:

{
  "media_id": "<sana verilen media id>",
  "primary_text": "<reklamın ana gövde metni>",
  "headline": "<kısa, çarpıcı başlık>",
  "description": "<kısa açıklama satırı>",
  "reasoning": "<bu metni neden önerdiğinin kısa gerekçesi>"
}

Hiçbir alan boş olamaz.
"""


def _validate_creative(creative, expected_media_id: str) -> bool:
    if not isinstance(creative, dict):
        return False
    for field in REQUIRED_FIELDS:
        if not creative.get(field):
            return False
    if creative["media_id"] != expected_media_id:
        return False
    if creative["primary_text"].strip() == "":
        return False
    return True


def generate_creative_for_post(post: dict) -> dict | None:
    """Tek bir gönderi için creative önerisi üretir; başarısız/şemaya uymayan
    durumda None döner (asla tahmini bir alan doldurmaz)."""
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    user_content = json.dumps(
        {
            "media_id": post.get("id"),
            "caption": post.get("caption", ""),
            "media_type": post.get("media_type"),
            "engagement_rate": post.get("engagement_rate"),
            "like_count": post.get("like_count"),
            "comments_count": post.get("comments_count"),
        },
        ensure_ascii=False,
    )

    message = client.messages.create(
        model=Config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")

    try:
        creative = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Creative JSON parse hatası (media_id=%s): %s. Ham cevap: %r", post.get("id"), exc, text[:1000])
        return None

    if not _validate_creative(creative, post.get("id")):
        logger.error("Şemaya uymayan/geçersiz creative elendi (media_id=%s): %r", post.get("id"), creative)
        return None

    if creative["primary_text"].strip().lower() == (post.get("caption") or "").strip().lower():
        logger.error(
            "Üretilen reklam metni organik caption ile birebir aynı (media_id=%s); elendi.",
            post.get("id"),
        )
        return None

    return creative


def generate_creatives(posts: list[dict]) -> list[dict]:
    creatives = []
    for post in posts:
        creative = generate_creative_for_post(post)
        if creative is not None:
            creatives.append(creative)
    return creatives
