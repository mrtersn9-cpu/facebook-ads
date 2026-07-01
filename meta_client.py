"""Facebook/Meta Marketing Graph API için ince bir istemci (requests tabanlı).

Not: Bu FAZ 0 iskeletidir. Mock mod, pagination ve ayrıntılı hata
sınıflandırması FAZ 1'de eklenecektir.
"""
import requests

from config import Config

REQUEST_TIMEOUT = 15


class MetaAPIError(Exception):
    """Graph API bir hata döndürdüğünde fırlatılır."""


class MetaClient:
    def __init__(self):
        self.access_token = Config.META_ACCESS_TOKEN
        self.ad_account_id = Config.META_AD_ACCOUNT_ID
        self.api_version = Config.META_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.access_token
        resp = requests.get(f"{self.base_url}/{path}", params=params, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    def _post(self, path: str, data: dict | None = None) -> dict:
        data = dict(data or {})
        data["access_token"] = self.access_token
        resp = requests.post(f"{self.base_url}/{path}", data=data, timeout=REQUEST_TIMEOUT)
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: requests.Response) -> dict:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise MetaAPIError(f"Graph API geçersiz JSON döndürdü: {resp.text[:500]}") from exc

        if resp.status_code >= 400 or "error" in payload:
            error = payload.get("error", {})
            raise MetaAPIError(
                f"Graph API hatası (code={error.get('code')}): {error.get('message', payload)}"
            )
        return payload

    def get_campaigns(self) -> list[dict]:
        data = self._get(
            f"act_{self.ad_account_id}/campaigns",
            {"fields": "id,name,status,objective"},
        )
        return data.get("data", [])

    def get_adsets(self, campaign_id: str | None = None) -> list[dict]:
        path = (
            f"{campaign_id}/adsets"
            if campaign_id
            else f"act_{self.ad_account_id}/adsets"
        )
        data = self._get(path, {"fields": "id,name,status,daily_budget,campaign_id"})
        return data.get("data", [])

    def get_insights(self, object_id: str, date_preset: str = "last_7d") -> list[dict]:
        data = self._get(
            f"{object_id}/insights",
            {
                "fields": "spend,impressions,clicks,actions,purchase_roas",
                "date_preset": date_preset,
            },
        )
        return data.get("data", [])

    def update_adset_budget(self, adset_id: str, daily_budget_cents: int) -> dict:
        return self._post(adset_id, {"daily_budget": daily_budget_cents})

    def pause_entity(self, entity_id: str) -> dict:
        return self._post(entity_id, {"status": "PAUSED"})

    def activate_entity(self, entity_id: str) -> dict:
        return self._post(entity_id, {"status": "ACTIVE"})
