"""Instagram gönderilerini engagement rate'e göre skorlayıp reklam adayı
olabilecek en iyi performanslı N tanesini seçer."""
from datetime import datetime, timezone

from config import Config


def _parse_timestamp(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _engagement_rate(media: dict, insights: dict) -> float:
    reach = insights.get("reach", 0)
    if not reach:
        return 0.0
    engagement = media.get("like_count", 0) + media.get("comments_count", 0)
    return engagement / reach


def select_top_posts(
    media_list: list[dict],
    insights_by_id: dict[str, dict],
    top_n: int | None = None,
    min_age_hours: float | None = None,
) -> list[dict]:
    """En iyi performans gösteren ilk N gönderiyi reklam adayı olarak döner.

    Her elemana `engagement_rate` alanı eklenir. Henüz yeterli veri
    toplamamış (min_age_hours'tan daha yeni) gönderiler elenir.
    """
    top_n = Config.IG_TOP_N_POSTS if top_n is None else top_n
    min_age_hours = Config.IG_MIN_POST_AGE_HOURS if min_age_hours is None else min_age_hours

    now = datetime.now(timezone.utc)
    candidates = []

    for media in media_list:
        posted_at = _parse_timestamp(media["timestamp"])
        age_hours = (now - posted_at).total_seconds() / 3600
        if age_hours < min_age_hours:
            continue

        insights = insights_by_id.get(media["id"], {})
        rate = _engagement_rate(media, insights)
        candidates.append({**media, "engagement_rate": rate})

    candidates.sort(key=lambda m: m["engagement_rate"], reverse=True)
    return candidates[:top_n]
