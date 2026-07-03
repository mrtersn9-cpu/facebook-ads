"""Instagram Graph API için ince bir istemci (meta_client.py ile aynı
desen: mock mod, rate-limit backoff, auth/rate-limit hata sınıflandırması).

Bu istemci sadece OKUMA yapar (organik gönderi verisi çeker); hiçbir yazma
uç noktası yoktur — reklam/kampanya oluşturma FAZ 12'de meta_client.py
üzerinden, ayrı bir guardrail katmanıyla yapılır.
"""
import json
import logging
import os
import time

import requests

from config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1

AUTH_ERROR_CODES = {190}
RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

MEDIA_FIELDS = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
# Not: eski tekil "engagement" metriği deprecated; reach + saved (+ like/comments
# zaten media alanlarında var) ile kendi engagement rate'imizi hesaplıyoruz.
INSIGHTS_METRICS = "reach,saved"


class IGAPIError(Exception):
    """Instagram Graph API bir hata döndürdüğünde fırlatılır."""


class IGAuthError(IGAPIError):
    """Token geçersiz/süresi dolmuş (code 190). Retry yapılmaz."""


class IGRateLimitError(IGAPIError):
    """Rate limit hatası (code 4/17/32/613). Backoff ile yeniden denenir."""


def _load_fixture(filename: str):
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


class IGClient:
    def __init__(self):
        self.access_token = Config.IG_ACCESS_TOKEN
        self.api_version = Config.IG_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    def _with_backoff(self, func, *args, **kwargs) -> dict:
        delay = BACKOFF_BASE_SECONDS
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except IGRateLimitError:
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(delay)
                delay *= 2

    def _do_get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.access_token
        resp = requests.get(f"{self.base_url}/{path}", params=params, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._with_backoff(self._do_get, path, params)

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise IGAPIError(f"IG Graph API geçersiz JSON döndürdü: {resp.text[:500]}") from exc

        if resp.status_code >= 400 or "error" in payload:
            error = payload.get("error", {})
            code = error.get("code")
            message = error.get("message", payload)

            if code in AUTH_ERROR_CODES:
                raise IGAuthError(
                    f"IG Graph API auth hatası (code={code}): {message}. Retry yapılmayacak."
                )
            if code in RATE_LIMIT_ERROR_CODES:
                raise IGRateLimitError(f"IG Graph API rate-limit hatası (code={code}): {message}")

            raise IGAPIError(f"IG Graph API hatası (code={code}): {message}")
        return payload

    def get_recent_media(self, ig_user_id: str, limit: int = 25) -> list[dict]:
        if Config.IG_MOCK_MODE:
            return _load_fixture("sample_ig_media.json")[:limit]

        data = self._get(f"{ig_user_id}/media", {"fields": MEDIA_FIELDS, "limit": limit})
        return data.get("data", [])

    def get_media_insights(self, media_id: str) -> dict:
        """{"reach": int, "saved": int} şeklinde basitleştirilmiş bir sözlük döner."""
        if Config.IG_MOCK_MODE:
            raw = _load_fixture("sample_ig_insights.json").get(media_id, [])
        else:
            data = self._get(f"{media_id}/insights", {"metric": INSIGHTS_METRICS})
            raw = data.get("data", [])

        result = {}
        for metric in raw:
            values = metric.get("values", [])
            if values:
                result[metric["name"]] = values[0].get("value", 0)
        return result
