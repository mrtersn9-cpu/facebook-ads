"""Facebook/Meta Marketing Graph API için ince bir istemci (requests tabanlı).

FAZ 1: mock mod (META_MOCK_MODE), pagination takibi ve auth/rate-limit hata
sınıflandırması eklendi.
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


class MetaAPIError(Exception):
    """Graph API bir hata döndürdüğünde fırlatılır."""


class MetaAuthError(MetaAPIError):
    """Token geçersiz/süresi dolmuş (code 190). Retry yapılmaz — token'ı
    yenilemek insan işidir."""


class MetaRateLimitError(MetaAPIError):
    """Rate limit hatası (code 4/17/32/613). Backoff ile yeniden denenir."""


def _load_fixture(filename: str):
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


class MetaClient:
    def __init__(self):
        self.access_token = Config.META_ACCESS_TOKEN
        self.ad_account_id = Config.META_AD_ACCOUNT_ID
        self.api_version = Config.META_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    # --- düşük seviye istek/backoff ---

    def _with_backoff(self, func, *args, **kwargs) -> dict:
        delay = BACKOFF_BASE_SECONDS
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except MetaRateLimitError:
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(delay)
                delay *= 2

    def _do_get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.access_token
        resp = requests.get(f"{self.base_url}/{path}", params=params, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    def _do_get_absolute(self, url: str) -> dict:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    def _do_post(self, path: str, data: dict | None = None) -> dict:
        data = dict(data or {})
        data["access_token"] = self.access_token
        resp = requests.post(f"{self.base_url}/{path}", data=data, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._with_backoff(self._do_get, path, params)

    def _post(self, path: str, data: dict | None = None) -> dict:
        return self._with_backoff(self._do_post, path, data)

    def _get_all_pages(self, path: str, params: dict | None = None) -> list[dict]:
        """paging.next takip edilerek tüm sayfaların "data" listelerini birleştirir."""
        payload = self._get(path, params)
        items = list(payload.get("data", []))

        next_url = payload.get("paging", {}).get("next")
        while next_url:
            payload = self._with_backoff(self._do_get_absolute, next_url)
            items.extend(payload.get("data", []))
            next_url = payload.get("paging", {}).get("next")

        return items

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise MetaAPIError(f"Graph API geçersiz JSON döndürdü: {resp.text[:500]}") from exc

        if resp.status_code >= 400 or "error" in payload:
            error = payload.get("error", {})
            code = error.get("code")
            message = error.get("message", payload)

            if code in AUTH_ERROR_CODES:
                raise MetaAuthError(
                    f"Graph API auth hatası (code={code}): {message}. "
                    "Token süresi dolmuş/geçersiz olabilir; retry yapılmayacak, "
                    "token'ın yenilenmesi gerekiyor."
                )
            if code in RATE_LIMIT_ERROR_CODES:
                raise MetaRateLimitError(f"Graph API rate-limit hatası (code={code}): {message}")

            raise MetaAPIError(f"Graph API hatası (code={code}): {message}")
        return payload

    # --- okuma uçları ---

    def get_campaigns(self) -> list[dict]:
        if Config.META_MOCK_MODE:
            return _load_fixture("sample_campaigns.json")
        return self._get_all_pages(
            f"act_{self.ad_account_id}/campaigns",
            {"fields": "id,name,status,objective"},
        )

    def get_adsets(self, campaign_id: str | None = None) -> list[dict]:
        if Config.META_MOCK_MODE:
            adsets = _load_fixture("sample_adsets.json")
            if campaign_id:
                adsets = [a for a in adsets if a.get("campaign_id") == campaign_id]
            return adsets

        path = f"{campaign_id}/adsets" if campaign_id else f"act_{self.ad_account_id}/adsets"
        return self._get_all_pages(path, {"fields": "id,name,status,daily_budget,campaign_id"})

    def get_insights(self, object_id: str, date_preset: str = "last_7d") -> list[dict]:
        if Config.META_MOCK_MODE:
            return _load_fixture("sample_insights.json").get(object_id, [])

        data = self._get(
            f"{object_id}/insights",
            {
                "fields": "spend,impressions,clicks,actions,purchase_roas",
                "date_preset": date_preset,
            },
        )
        return data.get("data", [])

    # --- yazma uçları ---

    def update_adset_budget(self, adset_id: str, daily_budget_cents: int) -> dict:
        return self._post(adset_id, {"daily_budget": daily_budget_cents})

    def pause_entity(self, entity_id: str) -> dict:
        return self._post(entity_id, {"status": "PAUSED"})

    def activate_entity(self, entity_id: str) -> dict:
        return self._post(entity_id, {"status": "ACTIVE"})


def check_token_expiry(client: MetaClient | None = None) -> None:
    """/debug_token ile access token'ın süresinin dolmasına az kaldıysa
    erken uyarı loglar. Best-effort: mock modda veya herhangi bir hata
    durumunda sessizce çıkar, ana pipeline'ı asla engellemez."""
    if Config.META_MOCK_MODE:
        return

    client = client or MetaClient()
    try:
        payload = client._get("debug_token", {"input_token": client.access_token})
    except MetaAPIError as exc:
        logger.warning("Token expiry kontrolü başarısız oldu: %s", exc)
        return

    data = payload.get("data", {})
    expires_at = data.get("expires_at")
    if not expires_at:
        return  # 0/None: süresiz (system user) token

    remaining_seconds = expires_at - time.time()
    remaining_days = remaining_seconds / 86400
    if remaining_days <= Config.TOKEN_EXPIRY_WARN_DAYS:
        logger.warning(
            "Meta access token %.1f gün içinde sona erecek! Token'ın yenilenmesi gerekiyor.",
            remaining_days,
        )
