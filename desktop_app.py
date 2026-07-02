"""Meta Ads AI Agent için basit bir masaüstü uygulaması (Tkinter).

CLAUDE.md'deki faz planına EK, isteğe bağlı bir kolaylık aracıdır —
guardrail/DRY_RUN mantığını hiçbir şekilde değiştirmez veya bypass etmez.
Sadece mevcut `main.py --once` ve `run_creative_pipeline.py --once`
komutlarını bir düğmeyle tetikler ve `logs/actions.jsonl`'i gösterir.

Tkinter Python ile birlikte gelir; ek bir paket kurulumu gerekmez.

Çalıştırma:
  python desktop_app.py
"""
import json
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from config import Config
from logger import ACTIONS_LOG_PATH
from reports.weekly_summary import summarize

MAX_LOG_ROWS = 50
RUN_TIMEOUT_SECONDS = 180

STATUS_FIELDS = [
    "DRY_RUN",
    "KILL_SWITCH",
    "META_MOCK_MODE",
    "IG_MOCK_MODE",
    "CAMPAIGN_OBJECTIVE",
    "META_AD_ACCOUNT_ID",
]


def read_recent_log_entries(limit: int = MAX_LOG_ROWS) -> list[dict]:
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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Meta Ads AI Agent")
        root.geometry("900x650")

        self._build_status_frame()
        self._build_buttons_frame()
        self._build_tabs()

        self.refresh()

    # --- arayüz kurulumu ---

    def _build_status_frame(self):
        frame = ttk.LabelFrame(self.root, text="Durum (salt okunur — değiştirmek için .env dosyasını düzenleyin)")
        frame.pack(fill="x", padx=10, pady=10)

        self.status_labels = {}
        for i, field in enumerate(STATUS_FIELDS):
            row, col = divmod(i, 3)
            ttk.Label(frame, text=f"{field}:").grid(row=row, column=col * 2, sticky="w", padx=5, pady=3)
            label = ttk.Label(frame, text="-", font=("Segoe UI", 9, "bold"))
            label.grid(row=row, column=col * 2 + 1, sticky="w", padx=5, pady=3)
            self.status_labels[field] = label

    def _build_buttons_frame(self):
        frame = ttk.Frame(self.root)
        frame.pack(fill="x", padx=10, pady=5)

        self.run_main_btn = ttk.Button(frame, text="▶ Bütçe Optimizasyonu Çalıştır", command=self.run_main)
        self.run_main_btn.pack(side="left", padx=5)

        self.run_creative_btn = ttk.Button(frame, text="▶ Creative Pipeline Çalıştır", command=self.run_creative)
        self.run_creative_btn.pack(side="left", padx=5)

        ttk.Button(frame, text="⟳ Yenile", command=self.refresh).pack(side="left", padx=5)

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=150)
        self.progress.pack(side="left", padx=10)

    def _build_tabs(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.output_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.output_text, text="Son Çalıştırma Çıktısı")
        self.output_text.insert(tk.END, "Henüz bir çalıştırma yapılmadı.\n")

        self.log_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.log_text, text="Loglar (logs/actions.jsonl)")

        self.summary_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.summary_text, text="Haftalık Özet")

    # --- veri yenileme ---

    def refresh(self):
        dry_run = Config.DRY_RUN
        kill_switch = Config.KILL_SWITCH

        self.status_labels["DRY_RUN"].config(text=str(dry_run), foreground=("dark green" if dry_run else "red"))
        self.status_labels["KILL_SWITCH"].config(text=str(kill_switch), foreground=("red" if kill_switch else "dark green"))
        self.status_labels["META_MOCK_MODE"].config(text=str(Config.META_MOCK_MODE))
        self.status_labels["IG_MOCK_MODE"].config(text=str(Config.IG_MOCK_MODE))
        self.status_labels["CAMPAIGN_OBJECTIVE"].config(text=Config.CAMPAIGN_OBJECTIVE)
        self.status_labels["META_AD_ACCOUNT_ID"].config(text=Config.META_AD_ACCOUNT_ID or "(ayarlanmadı)")

        entries = read_recent_log_entries()
        self.log_text.delete("1.0", tk.END)
        if not entries:
            self.log_text.insert(tk.END, "Henüz log kaydı yok.\n")
        for entry in entries:
            line = (
                f"[{entry.get('timestamp', '')}] {entry.get('adset_id', '-')} | "
                f"{entry.get('action', '-')} | {entry.get('status', '-')} | {entry.get('reason', '-')}\n"
            )
            self.log_text.insert(tk.END, line)

        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert(tk.END, summarize(days=7))

    # --- çalıştırma ---

    def _confirm(self, script_label: str) -> bool:
        if not Config.DRY_RUN:
            return messagebox.askyesno(
                "DİKKAT — DRY_RUN KAPALI",
                f"DRY_RUN=False! \"{script_label}\" çalıştırılırsa hesabınızda "
                "GERÇEK değişiklikler yapılabilir (bütçe/durum güncellemesi).\n\n"
                "Devam etmek istediğinize emin misiniz?",
                icon="warning",
            )
        return messagebox.askyesno("Onay", f"\"{script_label}\" bir kez çalıştırılacak (DRY_RUN=true, güvenli). Devam edilsin mi?")

    def run_main(self):
        if self._confirm("Bütçe Optimizasyonu (main.py --once)"):
            self._run_script_async("main.py")

    def run_creative(self):
        if self._confirm("Creative Pipeline (run_creative_pipeline.py --once)"):
            self._run_script_async("run_creative_pipeline.py")

    def _run_script_async(self, script_name: str):
        self.run_main_btn.config(state="disabled")
        self.run_creative_btn.config(state="disabled")
        self.progress.start(10)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, f"{script_name} çalıştırılıyor, lütfen bekleyin...\n")

        threading.Thread(target=self._run_script_worker, args=(script_name,), daemon=True).start()

    def _run_script_worker(self, script_name: str):
        try:
            result = subprocess.run(
                [sys.executable, script_name, "--once"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=RUN_TIMEOUT_SECONDS,
            )
            output = (
                f"Exit code: {result.returncode}\n\n"
                f"--- STDOUT ---\n{result.stdout}\n\n"
                f"--- STDERR ---\n{result.stderr}"
            )
        except subprocess.TimeoutExpired:
            output = f"{script_name}, {RUN_TIMEOUT_SECONDS} saniye içinde tamamlanmadı (timeout)."
        except Exception as exc:  # noqa: BLE001 — arayüzde göstermek için genel yakalama
            output = f"Beklenmeyen hata: {exc}"

        self.root.after(0, self._on_script_done, output)

    def _on_script_done(self, output: str):
        self.progress.stop()
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, output)
        self.run_main_btn.config(state="normal")
        self.run_creative_btn.config(state="normal")
        self.refresh()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
