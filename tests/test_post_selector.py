"""FAZ 11: post_selector.py'nin engagement rate'e göre sıralama ve
minimum yaş filtrelemesini doğru yaptığını doğrular."""
from datetime import datetime, timedelta, timezone

from post_selector import select_top_posts


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")


def test_selects_highest_engagement_rate_first():
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)

    media = [
        {"id": "low", "like_count": 10, "comments_count": 0, "timestamp": _iso(old_enough)},
        {"id": "high", "like_count": 100, "comments_count": 50, "timestamp": _iso(old_enough)},
    ]
    insights = {
        "low": {"reach": 1000},   # 10/1000 = 0.01
        "high": {"reach": 1000},  # 150/1000 = 0.15
    }

    result = select_top_posts(media, insights, top_n=2, min_age_hours=48)

    assert [m["id"] for m in result] == ["high", "low"]
    assert result[0]["engagement_rate"] == 0.15


def test_top_n_limits_results():
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [
        {"id": str(i), "like_count": i, "comments_count": 0, "timestamp": _iso(old_enough)}
        for i in range(10)
    ]
    insights = {str(i): {"reach": 100} for i in range(10)}

    result = select_top_posts(media, insights, top_n=3, min_age_hours=48)

    assert len(result) == 3
    assert [m["id"] for m in result] == ["9", "8", "7"]


def test_too_recent_posts_are_excluded():
    now = datetime.now(timezone.utc)
    too_recent = now - timedelta(hours=2)
    old_enough = now - timedelta(hours=100)

    media = [
        {"id": "fresh", "like_count": 1000, "comments_count": 1000, "timestamp": _iso(too_recent)},
        {"id": "aged", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
    ]
    insights = {"fresh": {"reach": 100}, "aged": {"reach": 100}}

    result = select_top_posts(media, insights, top_n=5, min_age_hours=48)

    assert [m["id"] for m in result] == ["aged"]


def test_missing_reach_gives_zero_rate_not_crash():
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [{"id": "no-insights", "like_count": 5, "comments_count": 5, "timestamp": _iso(old_enough)}]

    result = select_top_posts(media, insights_by_id={}, top_n=5, min_age_hours=48)

    assert result[0]["engagement_rate"] == 0.0


def test_defaults_come_from_config(monkeypatch):
    import config

    monkeypatch.setattr(config.Config, "IG_TOP_N_POSTS", 1)
    monkeypatch.setattr(config.Config, "IG_MIN_POST_AGE_HOURS", 48)

    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [
        {"id": "a", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
        {"id": "b", "like_count": 100, "comments_count": 0, "timestamp": _iso(old_enough)},
    ]
    insights = {"a": {"reach": 100}, "b": {"reach": 100}}

    result = select_top_posts(media, insights)

    assert len(result) == 1
    assert result[0]["id"] == "b"
