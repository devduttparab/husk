import os
import shutil
import threading
import csv
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# ---------- BRANDING ----------
APP_TITLE = "Mirakinetix Husk Cleaner"
BRAND_NAME = "Mirakinetix Technologies"
AUTHOR = "Devdutt Parab"
EMAIL = "mirakinetix@gmail.com"
LINKEDIN = "https://www.linkedin.com/in/devdutt-parab/"

# ---------- PATHS ----------
TEMP_TARGETS = [
    lambda: os.getenv("TEMP"),
    lambda: os.getenv("TMP"),
    lambda: r"C:\Windows\Temp",
]

# ---------- HELPERS ----------
def human_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def get_folder_size(path):
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    except:
        pass
    return total


def get_top_files(path, limit=10):
    files = []
    try:
        for root, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(root, f)
                try:
                    size = os.path.getsize(fp)
                    files.append((fp, size))
                except:
                    pass
    except:
        pass

    files.sort(key=lambda x: x[1], reverse=True)
    return files[:limit]


def delete_folder_contents(path, log, errors):
    total_deleted = 0
    try:
        for item in Path(path).iterdir():
            try:
                if item.is_file():
                    size = item.stat().st_size
                    item.unlink()
                    total_deleted += size
                elif item.is_dir():
                    size = get_folder_size(item)
                    shutil.rmtree(item, ignore_errors=True)
                    total_deleted += size
            except Exception as err:
                log(f"❌ {item}: {err}")
                errors.append(str(err))
    except Exception as e:
        log(f"❌ Access error: {e}")

    return total_deleted


# ---------- MAIN APP ----------
class HuskApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("820x560")

        self.errors = []
        self.scan_results = []
        self.total_scan_size = 0

        # Theme
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabel", background="#1e1e1e", foreground="#ffffff")
        style.configure("TButton", padding=6)

        self._build_ui()

        # Branding logs
        self.log(f"🚀 {APP_TITLE}")
        self.log(f"🏢 {BRAND_NAME}")
        self.log(f"👤 {AUTHOR}")
        self.log(f"📧 {EMAIL}")
        self.log(f"🔗 {LINKEDIN}\n")

    def _build_ui(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)

        btn = ttk.Frame(frame)
        btn.pack(pady=10)

        ttk.Button(btn, text="🔍 Scan", command=lambda: self.run_async(self._scan)).pack(side="left", padx=5)
        ttk.Button(btn, text="🧹 Clean", command=lambda: self.run_async(self._clean)).pack(side="left", padx=5)
        ttk.Button(btn, text="⚡ Optimize", command=lambda: self.run_async(self._optimize)).pack(side="left", padx=5)
        ttk.Button(btn, text="📊 Top Files", command=lambda: self.run_async(self._top_files)).pack(side="left", padx=5)
        ttk.Button(btn, text="📁 Export CSV", command=self._export_csv).pack(side="left", padx=5)
        ttk.Button(btn, text="ℹ About", command=self._about).pack(side="left", padx=5)

        self.progress = ttk.Progressbar(frame, length=500)
        self.progress.pack(pady=5)

        self.log_box = scrolledtext.ScrolledText(
            frame,
            bg="#111",
            fg="#ddd",
            insertbackground="white"
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        footer = ttk.Label(
            frame,
            text=f"© {BRAND_NAME} | Built by {AUTHOR}",
            anchor="center"
        )
        footer.pack(side="bottom", pady=5)

    def log(self, msg):
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)

    def run_async(self, func):
        threading.Thread(target=func, daemon=True).start()

    # ---------- SCAN ----------
    def _scan(self):
        self.log(f"\n🔍 Scan started by {AUTHOR}\n")

        self.scan_results = []
        self.total_scan_size = 0

        paths = [p() for p in TEMP_TARGETS if p()]
        self.progress["maximum"] = len(paths)

        for i, path in enumerate(paths, 1):
            size = get_folder_size(Path(path))
            self.scan_results.append((path, size))
            self.total_scan_size += size

            self.log(f"{path} → {human_size(size)}")
            self.progress["value"] = i

        self._health_score()

    # ---------- CLEAN ----------
    def _clean(self):
        if not messagebox.askyesno("Confirm", "Delete temp files?"):
            return

        self.log(f"\n🧹 Cleanup initiated by {AUTHOR}\n")

        total = 0
        paths = [p() for p in TEMP_TARGETS if p()]
        self.progress["maximum"] = len(paths)

        for i, path in enumerate(paths, 1):
            size = delete_folder_contents(Path(path), self.log, self.errors)
            total += size
            self.progress["value"] = i

        self.log(f"\n✅ Freed: {human_size(total)}")

        if self.errors:
            messagebox.showwarning("Warnings", f"{len(self.errors)} errors occurred.")
            self.errors.clear()

    # ---------- OPTIMIZE ----------
    def _optimize(self):
        if not messagebox.askyesno("Optimize", "Scan + Clean system?"):
            return

        self.log("\n⚡ Full optimization started\n")
        self._scan()
        self._clean()
        self.log("\n🚀 Optimization completed!")

    # ---------- TOP FILES ----------
    def _top_files(self):
        self.log("\n📊 Top 10 Largest Files:\n")

        all_files = []
        for path, _ in self.scan_results:
            all_files.extend(get_top_files(Path(path)))

        all_files.sort(key=lambda x: x[1], reverse=True)
        for f, size in all_files[:10]:
            self.log(f"{human_size(size)} → {f}")

    # ---------- EXPORT ----------
    def _export_csv(self):
        file = filedialog.asksaveasfilename(defaultextension=".csv")

        if not file:
            return

        with open(file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Path", "Size"])

            for path, size in self.scan_results:
                writer.writerow([path, human_size(size)])

        self.log(f"📁 Report exported: {file}")

    # ---------- HEALTH ----------
    def _health_score(self):
        if self.total_scan_size == 0:
            score = 100
        elif self.total_scan_size < 500 * 1024 * 1024:
            score = 80
        elif self.total_scan_size < 2 * 1024 * 1024 * 1024:
            score = 60
        else:
            score = 40

        self.log(f"\n💡 System Health Score: {score}/100")

    # ---------- ABOUT ----------
    def _about(self):
        messagebox.showinfo(
            "About",
            f"{APP_TITLE}\n\n"
            f"Developed by: {AUTHOR}\n"
            f"{BRAND_NAME}\n\n"
            f"Email: {EMAIL}\n"
            f"LinkedIn:\n{LINKEDIN}"
        )

    # ---------- SCHEDULER ----------
    def start_scheduler(self):
        def loop():
            while True:
                self._clean()
                time.sleep(3600)

        threading.Thread(target=loop, daemon=True).start()


# ---------- RUN ----------
if __name__ == "__main__":
    app = HuskApp()
    # app.start_scheduler()  # enable if needed
    app.mainloop()