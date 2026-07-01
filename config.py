"""Ortam değişkenlerini okur ve guardrail sabitlerini tek bir yerden sunar."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val not in (None, "") else default


def _int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val not in (None, "") else default


class ConfigError(Exception):
    """Zorunlu bir ortam değişkeni eksik veya geçersiz olduğunda fırlatılır."""


class Config:
    # --- Meta / Facebook ---
    META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
    META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
    META_API_VERSION = os.environ.get("META_API_VERSION", "v25.0")
    META_MOCK_MODE = _bool("META_MOCK_MODE", False)

    # --- Anthropic ---
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    # --- Operasyon ---
    DRY_RUN = _bool("DRY_RUN", True)
    KILL_SWITCH = _bool("KILL_SWITCH", False)
    RUN_INTERVAL_HOURS = _float("RUN_INTERVAL_HOURS", 4)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # --- Guardrail sabitleri ---
    MAX_DAILY_BUDGET_TOTAL = _float("MAX_DAILY_BUDGET_TOTAL", 100.0)
    MAX_BUDGET_CHANGE_PERCENT = _float("MAX_BUDGET_CHANGE_PERCENT", 20.0)
    MIN_SPEND_BEFORE_ACTION = _float("MIN_SPEND_BEFORE_ACTION", 5.0)
    MAX_ACTIONS_PER_RUN = _int("MAX_ACTIONS_PER_RUN", 10)

    # --- Bildirim (opsiyonel) ---
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

    # --- Kademeli canlıya alma (FAZ 8) ---
    # Boşsa hesaptaki tüm aktif ad set'ler kapsam dahilindedir. Doldurulursa
    # sadece adında bu alt dizeyi (case-insensitive) içeren kampanyalardaki
    # ad set'ler işlenir — staged rollout'ta botun etkisini tek bir düşük
    # riskli kampanya grubuna sınırlamak için kullanılır.
    SCOPE_CAMPAIGN_NAME_FILTER = os.environ.get("SCOPE_CAMPAIGN_NAME_FILTER", "")

    @classmethod
    def validate(cls) -> None:
        """Zorunlu değişkenleri kontrol eder; eksikse anlamlı bir hata fırlatır.

        Mock modundayken gerçek Meta kimlik bilgileri gerekmez.
        """
        missing = []

        if not cls.META_MOCK_MODE:
            if not cls.META_ACCESS_TOKEN:
                missing.append("META_ACCESS_TOKEN")
            if not cls.META_AD_ACCOUNT_ID:
                missing.append("META_AD_ACCOUNT_ID")

        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")

        if missing:
            raise ConfigError(
                "Eksik zorunlu ortam değişken(ler)i: "
                + ", ".join(missing)
                + ". Lütfen .env dosyanızı .env.example'a göre doldurun."
            )
