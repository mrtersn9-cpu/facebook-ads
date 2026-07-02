"""Meta Ads AI Agent için basit, salt-güvenlik-bilgili bir web dashboard'u.

Bu, CLAUDE.md'deki faz planına EK, isteğe bağlı bir kolaylık aracıdır —
guardrail/DRY_RUN mantığını hiçbir şekilde değiştirmez veya bypass etmez.
Sadece mevcut `main.py --once` ve `run_creative_pipeline.py --once`
komutlarını bir düğmeyle tetikler ve `logs/actions.jsonl`'i okunabilir
şekilde gösterir.

Güvenlik notu: sadece localhost'ta (127.0.0.1) dinler. Gerçek hesap
kimlik bilgileriyle çalıştığı için internete açık bir sunucuda
kimlik doğrulaması eklemeden ASLA yayınlamayın.

Çalıştırma:
  python web_ui.py
  Tarayıcıda http://127.0.0.1:5000 açın.
"""
import json
import subprocess
import sys

from flask import Flask, redirect, render_template, url_for

from config import Config
from logger import ACTIONS_LOG_PATH
from reports.weekly_summary import summarize

app = Flask(__name__)

MAX_LOG_ROWS = 50
RUN_TIMEOUT_SECONDS = 180

_last_run_result: dict | None = None


def _read_recent_log_entries(limit: int = MAX_LOG_ROWS) -> list[dict]:
    entries = []
    try:
        with open(ACTIONS_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []

    return list(reversed(entries))[:limit]


def _run_script(script_name: str) -> dict:
    """main.py veya run_creative_pipeline.py'yi --once ile alt süreç olarak
    çalıştırır; guardrail/DRY_RUN davranışı script'in kendi mantığına
    aittir, burada hiçbir şekilde değiştirilmez."""
    result = subprocess.run(
        [sys.executable, script_name, "--once"],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
        cwd=".",
    )
    return {
        "script": script_name,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.route("/")
def dashboard():
    config_status = {
        "DRY_RUN": Config.DRY_RUN,
        "KILL_SWITCH": Config.KILL_SWITCH,
        "META_MOCK_MODE": Config.META_MOCK_MODE,
        "IG_MOCK_MODE": Config.IG_MOCK_MODE,
        "CAMPAIGN_OBJECTIVE": Config.CAMPAIGN_OBJECTIVE,
        "META_AD_ACCOUNT_ID": Config.META_AD_ACCOUNT_ID or "(ayarlanmadı)",
    }
    entries = _read_recent_log_entries()
    weekly = summarize(days=7)
    return render_template(
        "dashboard.html",
        config_status=config_status,
        entries=entries,
        weekly=weekly,
        last_run=_last_run_result,
    )


@app.route("/run/main", methods=["POST"])
def run_main():
    global _last_run_result
    _last_run_result = _run_script("main.py")
    return redirect(url_for("dashboard"))


@app.route("/run/creative", methods=["POST"])
def run_creative():
    global _last_run_result
    _last_run_result = _run_script("run_creative_pipeline.py")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
