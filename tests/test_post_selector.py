"""FAZ 11: post_selector.py'nin engagement rate'e göre sıralama ve
minimum yaş filtrelemesini doğru yaptığını doğrular."""
from datetime import datetime, timedelta, timezone

import pytest

import config
from post_selector import select_top_posts


@pytest.fixture(autouse=True)
def _default_no_video_filter(monkeypatch):
    # Gerçek .env'de IG_ONLY_VIDEO_POSTS=true olabilir; testleri buna
    # bağımlı kılmamak için varsayılanı burada sabitliyoruz. Video filtresini
    # test eden case'ler kendi içinde açıkça True'ya çeker.
    monkeypatch.setattr(config.Config, "IG_ONLY_VIDEO_POSTS", False)


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


def test_only_video_excludes_image_posts_when_requested():
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [
        {"id": "img", "media_type": "IMAGE", "like_count": 1000, "comments_count": 0, "timestamp": _iso(old_enough)},
        {"id": "vid", "media_type": "VIDEO", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
    ]
    insights = {"img": {"reach": 100}, "vid": {"reach": 100}}

    result = select_top_posts(media, insights, top_n=5, min_age_hours=48, only_video=True)

    assert [m["id"] for m in result] == ["vid"]


def test_only_video_false_includes_images_too():
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [
        {"id": "img", "media_type": "IMAGE", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
        {"id": "vid", "media_type": "VIDEO", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
    ]
    insights = {"img": {"reach": 100}, "vid": {"reach": 100}}

    result = select_top_posts(media, insights, top_n=5, min_age_hours=48, only_video=False)

    assert {m["id"] for m in result} == {"img", "vid"}


def test_only_video_defaults_to_config(monkeypatch):
    monkeypatch.setattr(config.Config, "IG_ONLY_VIDEO_POSTS", True)
    now = datetime.now(timezone.utc)
    old_enough = now - timedelta(hours=100)
    media = [
        {"id": "img", "media_type": "IMAGE", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
        {"id": "vid", "media_type": "VIDEO", "like_count": 1, "comments_count": 0, "timestamp": _iso(old_enough)},
    ]
    insights = {"img": {"reach": 100}, "vid": {"reach": 100}}

    result = select_top_posts(media, insights, top_n=5, min_age_hours=48)

    assert [m["id"] for m in result] == ["vid"]
