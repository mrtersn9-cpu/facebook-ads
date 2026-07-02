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

import approval_queue
from action_executor import execute_actions
from config import Config
from ig_client import IGClient
from logger import ACTIONS_LOG_PATH, log_action
from post_selector import list_candidate_posts
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
    "AUTOMATION_MODE",
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

        self.post_vars: dict[str, tk.BooleanVar] = {}

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

        posts_tab = ttk.Frame(notebook)
        notebook.add(posts_tab, text="Gönderi Seç (Instagram)")
        self._build_post_selector_tab(posts_tab)

        approval_tab = ttk.Frame(notebook)
        notebook.add(approval_tab, text="Onay Kuyruğu")
        self._build_approval_tab(approval_tab)

        self.output_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.output_text, text="Son Çalıştırma Çıktısı")
        self.output_text.insert(tk.END, "Henüz bir çalıştırma yapılmadı.\n")

        self.log_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.log_text, text="Loglar (logs/actions.jsonl)")

        self.summary_text = scrolledtext.ScrolledText(notebook, wrap="word")
        notebook.add(self.summary_text, text="Haftalık Özet")

    def _build_post_selector_tab(self, parent: ttk.Frame):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=5, pady=5)

        ttk.Button(toolbar, text="⟳ Gönderileri Getir", command=self.fetch_posts).pack(side="left", padx=5)
        self.run_selected_btn = ttk.Button(
            toolbar, text="▶ Seçili Gönderiler İçin Reklam Oluştur",
            command=self.run_selected_posts, state="disabled",
        )
        self.run_selected_btn.pack(side="left", padx=5)

        list_container = ttk.Frame(parent)
        list_container.pack(fill="both", expand=True, padx=5, pady=5)

        canvas = tk.Canvas(list_container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        self.posts_list_frame = ttk.Frame(canvas)
        self.posts_list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.posts_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            self.posts_list_frame,
            text="Gönderileri görmek için '⟳ Gönderileri Getir' düğmesine basın.",
        ).pack(anchor="w", padx=5, pady=5)

    def _build_approval_tab(self, parent: ttk.Frame):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=5, pady=5)
        ttk.Button(toolbar, text="⟳ Yenile", command=self.refresh_approval_queue).pack(side="left", padx=5)
        ttk.Label(
            toolbar,
            text="AUTOMATION_MODE=onayli iken guardrail'den geçen aksiyonlar burada onayınızı bekler.",
        ).pack(side="left", padx=10)

        list_container = ttk.Frame(parent)
        list_container.pack(fill="both", expand=True, padx=5, pady=5)

        canvas = tk.Canvas(list_container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        self.approval_list_frame = ttk.Frame(canvas)
        self.approval_list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.approval_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # --- onay kuyruğu ---

    def refresh_approval_queue(self):
        for widget in self.approval_list_frame.winfo_children():
            widget.destroy()

        pending = approval_queue.list_pending()
        if not pending:
            ttk.Label(self.approval_list_frame, text="Onay bekleyen aksiyon yok.").pack(
                anchor="w", padx=5, pady=5
            )
            return

        for entry in pending:
            self._build_approval_row(entry)

    def _build_approval_row(self, entry: dict):
        action = entry.get("action", {})
        row = ttk.Frame(self.approval_list_frame, relief="groove", borderwidth=1)
        row.pack(fill="x", padx=5, pady=3)

        detail = f" -> {action.get('new_daily_budget')}" if action.get("action") == "update_budget" else ""
        text = (
            f"[{entry.get('queued_at', '-')}] adset={action.get('adset_id')} | "
            f"{action.get('action')}{detail} | güven={action.get('guven_skoru', '-')}\n"
            f"Gerekçe: {action.get('reason', '-')}"
        )
        ttk.Label(row, text=text, wraplength=650, justify="left").pack(side="left", fill="x", expand=True, padx=5, pady=5)

        btns = ttk.Frame(row)
        btns.pack(side="right", padx=5)
        ttk.Button(btns, text="✅ Onayla", command=lambda: self.approve_entry(entry)).pack(side="top", pady=2)
        ttk.Button(btns, text="❌ Reddet", command=lambda: self.reject_entry(entry)).pack(side="top", pady=2)

    def approve_entry(self, entry: dict):
        action = entry.get("action", {})
        if not messagebox.askyesno(
            "Onay",
            f"adset={action.get('adset_id')} için '{action.get('action')}' aksiyonunu onaylayıp "
            f"{'GERÇEK olarak uygulamak' if not Config.DRY_RUN else 'simüle etmek (DRY_RUN=true)'} "
            "istediğinize emin misiniz?",
            icon="warning" if not Config.DRY_RUN else "question",
        ):
            return
        threading.Thread(target=self._approve_entry_worker, args=(entry,), daemon=True).start()

    def _approve_entry_worker(self, entry: dict):
        resolved = approval_queue.resolve(entry["id"], "approved")
        if resolved:
            execute_actions([resolved["action"]])
        self.root.after(0, self.refresh_approval_queue)

    def reject_entry(self, entry: dict):
        action = entry.get("action", {})
        if not messagebox.askyesno("Reddet", f"adset={action.get('adset_id')} için bu aksiyon reddedilsin mi?"):
            return
        resolved = approval_queue.resolve(entry["id"], "rejected")
        if resolved:
            log_action(
                {
                    "adset_id": action.get("adset_id"),
                    "action": action.get("action"),
                    "status": "rejected",
                    "reason": f"İnsan tarafından onay kuyruğunda reddedildi. Orijinal gerekçe: {action.get('reason', '')}",
                }
            )
        self.refresh_approval_queue()

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
        self.status_labels["AUTOMATION_MODE"].config(text=Config.AUTOMATION_MODE)

        self.refresh_approval_queue()

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

    # --- gönderi seçimi (Instagram) ---

    def fetch_posts(self):
        for widget in self.posts_list_frame.winfo_children():
            widget.destroy()
        ttk.Label(self.posts_list_frame, text="Gönderiler getiriliyor, lütfen bekleyin...").pack(
            anchor="w", padx=5, pady=5
        )
        self.run_selected_btn.config(state="disabled")
        threading.Thread(target=self._fetch_posts_worker, daemon=True).start()

    def _fetch_posts_worker(self):
        error = None
        posts = []
        try:
            client = IGClient()
            media = client.get_recent_media(Config.IG_BUSINESS_ACCOUNT_ID)
            insights_by_id = {m["id"]: client.get_media_insights(m["id"]) for m in media}
            posts = list_candidate_posts(media, insights_by_id)
        except Exception as exc:  # noqa: BLE001 — arayüzde göstermek için genel yakalama
            error = str(exc)

        self.root.after(0, self._on_posts_fetched, posts, error)

    def _on_posts_fetched(self, posts: list[dict], error: str | None):
        for widget in self.posts_list_frame.winfo_children():
            widget.destroy()
        self.post_vars = {}

        if error:
            ttk.Label(self.posts_list_frame, text=f"Hata: {error}", foreground="red").pack(
                anchor="w", padx=5, pady=5
            )
            return

        if not posts:
            ttk.Label(self.posts_list_frame, text="Uygun gönderi bulunamadı (yaş/tür filtresine takılmış olabilir).").pack(
                anchor="w", padx=5, pady=5
            )
            return

        for post in posts:
            var = tk.BooleanVar(value=False)
            caption = (post.get("caption") or "(caption yok)").replace("\n", " ")
            if len(caption) > 90:
                caption = caption[:90] + "…"
            label_text = (
                f"[{post.get('media_type', '?')}] engagement={post['engagement_rate']:.3f} "
                f"| ♥{post.get('like_count', 0)} 💬{post.get('comments_count', 0)} | {caption}"
            )
            ttk.Checkbutton(self.posts_list_frame, text=label_text, variable=var).pack(
                anchor="w", padx=5, pady=2
            )
            self.post_vars[post["id"]] = var

        self.run_selected_btn.config(state="normal")

    def run_selected_posts(self):
        selected_ids = [media_id for media_id, var in self.post_vars.items() if var.get()]
        if not selected_ids:
            messagebox.showinfo("Seçim yok", "Lütfen en az bir gönderi seçin.")
            return

        label = f"Seçili {len(selected_ids)} gönderi için Creative Pipeline"
        if self._confirm(label):
            self._run_script_async("run_creative_pipeline.py", extra_args=["--media-ids", ",".join(selected_ids)])

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

    def _run_script_async(self, script_name: str, extra_args: list[str] | None = None):
        self.run_main_btn.config(state="disabled")
        self.run_creative_btn.config(state="disabled")
        self.run_selected_btn.config(state="disabled")
        self.progress.start(10)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, f"{script_name} çalıştırılıyor, lütfen bekleyin...\n")

        threading.Thread(target=self._run_script_worker, args=(script_name, extra_args), daemon=True).start()

    def _run_script_worker(self, script_name: str, extra_args: list[str] | None = None):
        try:
            cmd = [sys.executable, script_name, "--once", *(extra_args or [])]
            result = subprocess.run(
                cmd,
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
        self.run_selected_btn.config(state="normal" if self.post_vars else "disabled")
        self.refresh()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
