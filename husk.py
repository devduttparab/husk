"""
Husk  
VERSION = "1.0"
----
A local GUI tool (Tkinter, standard library only) for safely stripping
the bloat off a Windows PC and speeding it up:

Author: Devdutt Parab
Email:  devduttparab@gmail.com
LinkedIn: https://www.linkedin.com/in/devdutt-parab/

  - Quick Cleanup: temp files, Recycle Bin, browser caches
  - Startup Manager: enable/disable programs that launch at boot
  - Visual Effects: toggle animations/transparency/shadows for performance
  - Services: safely start/stop/set-startup-type for a curated list of
    optional Windows services
  - System Info: RAM / disk / CPU snapshot

REQUIREMENTS
  - Windows 10/11
  - Python 3.9+ (uses only the standard library - no pip installs needed)
  - Run as Administrator for Startup Manager / Services / some cleanup
    operations. The app will tell you if it isn't elevated and offers a
    one-click "Restart as Administrator" button.

Run with:
    python husk.py

SAFETY NOTES
  - This tool never edits the registry blindly - every write is a known,
    documented, reversible key (things Windows' own Settings app / System
    Restore already exposes).
  - Startup items are never deleted permanently; disabling backs them up
    to a local JSON file (startup_backup.json next to this script) so
    they can be restored.
  - The Services tab only exposes a curated list of optional services
    (see SAFE_SERVICES below) - not the full service list - to avoid
    someone accidentally disabling something critical.
  - Nothing here touches Windows Update, security services, drivers, or
    anything not in the curated safe list.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox
from pathlib import Path

AUTHOR_NAME = "Devdutt Parab"
AUTHOR_EMAIL = "devduttparab@gmail.com"
AUTHOR_LINKEDIN = "https://www.linkedin.com/in/devdutt-parab/"

IS_WINDOWS = sys.platform.startswith("win")
BACKUP_FILE = Path(__file__).with_name("startup_backup.json")

# --------------------------------------------------------------------------
# Curated list of optional services that are generally safe for a typical
# home user to stop/disable if they don't use the related feature.
# Format: registry/service name -> (display name, description, risk note)
# --------------------------------------------------------------------------
SAFE_SERVICES = {
    "SysMain": (
        "SysMain (Superfetch)",
        "Preloads frequently used apps into RAM. Helps on HDDs, can add "
        "overhead on SSDs.",
        "Safe to disable on SSD systems.",
    ),
    "DiagTrack": (
        "Connected User Experiences and Telemetry",
        "Collects diagnostic and usage data sent to Microsoft.",
        "Safe to disable for privacy/performance; purely optional.",
    ),
    "WSearch": (
        "Windows Search",
        "Indexes files for fast Start Menu / File Explorer search.",
        "Disabling makes file search slower but frees background CPU/disk.",
    ),
    "PrintNotify": (
        "Printer Extensions and Notifications",
        "Printer notifications and driver support.",
        "Safe to disable if you don't print.",
    ),
    "Fax": (
        "Fax Service",
        "Handles sending/receiving faxes.",
        "Safe to disable - almost nobody uses this.",
    ),
    "TabletInputService": (
        "Touch Keyboard and Handwriting Panel Service",
        "Supports touch keyboard / handwriting input.",
        "Safe to disable on a desktop/laptop with no touchscreen.",
    ),
    "RemoteRegistry": (
        "Remote Registry",
        "Lets remote users modify registry settings on this PC.",
        "Off by default on most systems; safe to keep disabled.",
    ),
}

TEMP_TARGETS = [
    lambda: os.environ.get("TEMP"),
    lambda: os.environ.get("TMP"),
    lambda: str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp"),
]

BROWSER_CACHE_TARGETS = {
    "Chrome": lambda local: local / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
    "Edge": lambda local: local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
    "Firefox": lambda local: local / "Mozilla" / "Firefox" / "Profiles",
}


# --------------------------------------------------------------------------
# Windows-only helpers (guarded so the file can at least be imported /
# read on non-Windows systems for review purposes)
# --------------------------------------------------------------------------
def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )


def folder_size(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def delete_folder_contents(path: Path, log):
    if not path or not path.exists():
        return 0
    freed = 0
    locked_count = 0
    other_errors = []
    for entry in path.iterdir():
        try:
            size = folder_size(entry) if entry.is_dir() else entry.stat().st_size
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            freed += size
        except PermissionError:
            # File is open/locked by another running process - expected
            # and safe to skip; deleting it could destabilize whatever
            # has it open.
            locked_count += 1
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                locked_count += 1
            else:
                other_errors.append(f"{entry.name}: {e}")
        except Exception as e:
            other_errors.append(f"{entry.name}: {e}")

    if locked_count:
        log(f"  Skipped {locked_count} file(s) currently in use by another program.")
    for err in other_errors:
        log(f"  ! could not remove {err}")
    return freed


def empty_recycle_bin():
    # SHEmptyRecycleBinW flags: 0x1 no confirm, 0x2 no progress, 0x4 no sound
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000001 | 0x00000002 | 0x00000004)


# --------------------------------------------------------------------------
# Registry-based helpers (Startup + Visual Effects)
# --------------------------------------------------------------------------
if IS_WINDOWS:
    import winreg

RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") if IS_WINDOWS else None,
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run") if IS_WINDOWS else None,
]


def list_startup_items():
    items = []
    if not IS_WINDOWS:
        return items
    for hive, subkey in RUN_KEYS:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        items.append({"hive": hive, "subkey": subkey, "name": name, "value": value})
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            pass
    return items


def load_backup():
    if BACKUP_FILE.exists():
        try:
            return json.loads(BACKUP_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_backup(data):
    BACKUP_FILE.write_text(json.dumps(data, indent=2))


def hive_name(hive):
    return "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"


def hive_from_name(name):
    return winreg.HKEY_CURRENT_USER if name == "HKCU" else winreg.HKEY_LOCAL_MACHINE


def disable_startup_item(item, log):
    backup = load_backup()
    key_id = f"{hive_name(item['hive'])}|{item['subkey']}|{item['name']}"
    backup[key_id] = item["value"]
    save_backup(backup)
    try:
        with winreg.OpenKey(item["hive"], item["subkey"], 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, item["name"])
        log(f"Disabled startup item: {item['name']}")
    except Exception as e:
        log(f"! failed to disable {item['name']}: {e}")


def restore_startup_item(key_id, log):
    backup = load_backup()
    value = backup.pop(key_id, None)
    save_backup(backup)
    if value is None:
        return
    hive_str, subkey, name = key_id.split("|", 2)
    try:
        with winreg.OpenKey(hive_from_name(hive_str), subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        log(f"Restored startup item: {name}")
    except Exception as e:
        log(f"! failed to restore {name}: {e}")


# Visual effects registry targets: (hive, subkey, value_name, on_value, off_value, value_type)
VISUAL_EFFECTS = {
    "Animations (minimize/maximize)": (
        winreg.HKEY_CURRENT_USER if IS_WINDOWS else None,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
        "TaskbarAnimations", 1, 0, "DWORD",
    ),
    "Menu animations": (
        winreg.HKEY_CURRENT_USER if IS_WINDOWS else None,
        r"Control Panel\Desktop",
        "MenuShowDelay", "400", "0", "SZ",
    ),
    "Transparency effects": (
        winreg.HKEY_CURRENT_USER if IS_WINDOWS else None,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "EnableTransparency", 1, 0, "DWORD",
    ),
    "Window shadows": (
        winreg.HKEY_CURRENT_USER if IS_WINDOWS else None,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
        "ListviewShadow", 1, 0, "DWORD",
    ),
    "Smooth scrolling in list boxes": (
        winreg.HKEY_CURRENT_USER if IS_WINDOWS else None,
        r"Control Panel\Desktop",
        "SmoothScroll", "1", "0", "SZ",
    ),
}


def set_visual_effect(name, enabled, log):
    hive, subkey, value_name, on_val, off_val, vtype = VISUAL_EFFECTS[name]
    val = on_val if enabled else off_val
    try:
        with winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
            if vtype == "DWORD":
                winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, val)
            else:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, val)
        log(f"{'Enabled' if enabled else 'Disabled'}: {name}")
    except Exception as e:
        log(f"! failed to set {name}: {e}")


def get_visual_effect(name):
    hive, subkey, value_name, on_val, off_val, vtype = VISUAL_EFFECTS[name]
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return val == on_val
    except Exception:
        return None  # unknown / not set


# --------------------------------------------------------------------------
# Services helpers (uses sc.exe - no admin needed to query, admin needed
# to change)
# --------------------------------------------------------------------------
def sc_query(name):
    try:
        out = subprocess.run(
            ["sc", "query", name], capture_output=True, text=True, timeout=5
        ).stdout
        if "RUNNING" in out:
            return "Running"
        if "STOPPED" in out:
            return "Stopped"
        return "Unknown"
    except Exception:
        return "Unknown"


def sc_set_startup(name, mode, log):
    # mode: "disabled", "demand" (manual), "auto"
    try:
        result = subprocess.run(
            ["sc", "config", name, "start=", mode],
            capture_output=True, text=True, timeout=5,
        )
        log(f"{name} startup type set to {mode}: {result.stdout.strip() or 'OK'}")
    except Exception as e:
        log(f"! failed to set startup type for {name}: {e}")


def sc_stop(name, log):
    try:
        result = subprocess.run(["sc", "stop", name], capture_output=True, text=True, timeout=5)
        log(f"Stopped {name}: {result.stdout.strip() or 'OK'}")
    except Exception as e:
        log(f"! failed to stop {name}: {e}")


def sc_start(name, log):
    try:
        result = subprocess.run(["sc", "start", name], capture_output=True, text=True, timeout=5)
        log(f"Started {name}: {result.stdout.strip() or 'OK'}")
    except Exception as e:
        log(f"! failed to start {name}: {e}")


# --------------------------------------------------------------------------
# System info
# --------------------------------------------------------------------------
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_memory_info():
    if not IS_WINDOWS:
        return None
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat


def get_disk_info():
    drives = []
    if not IS_WINDOWS:
        return drives
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            letter = f"{chr(65 + i)}:\\"
            try:
                usage = shutil.disk_usage(letter)
                drives.append((letter, usage))
            except OSError:
                pass
    return drives


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
class OptimizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Husk")
        self.geometry("820x600")
        self.minsize(720, 520)

        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self.cleanup_tab = ttk.Frame(self.notebook)
        self.startup_tab = ttk.Frame(self.notebook)
        self.visual_tab = ttk.Frame(self.notebook)
        self.services_tab = ttk.Frame(self.notebook)
        self.sysinfo_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.cleanup_tab, text="Quick Cleanup")
        self.notebook.add(self.startup_tab, text="Startup Manager")
        self.notebook.add(self.visual_tab, text="Visual Effects")
        self.notebook.add(self.services_tab, text="Services")
        self.notebook.add(self.sysinfo_tab, text="System Info")

        self._build_cleanup_tab()
        self._build_startup_tab()
        self._build_visual_tab()
        self._build_services_tab()
        self._build_sysinfo_tab()

        self._build_log_panel()
        self._build_footer()

        if not IS_WINDOWS:
            self.log("This tool is designed for Windows. Some features are disabled "
                      "in this preview environment.")

    # ---------------------------------------------------------------- header
    def _build_header(self):
        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=8, pady=8)
        admin = is_admin()
        status = "Administrator ✓" if admin else "Not running as Administrator"
        color = "#1a7f37" if admin else "#b35900"
        lbl = tk.Label(frame, text=f"Status: {status}", fg=color, font=("Segoe UI", 10, "bold"))
        lbl.pack(side="left")
        if not admin and IS_WINDOWS:
            btn = ttk.Button(frame, text="Restart as Administrator", command=self._elevate)
            btn.pack(side="right")

    def _elevate(self):
        relaunch_as_admin()
        self.destroy()

    # -------------------------------------------------------------- footer
    def _build_footer(self):
        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(frame, text=f"Made by {AUTHOR_NAME}  ·  ", foreground="#666").pack(side="left")

        email_lbl = tk.Label(frame, text=AUTHOR_EMAIL, fg="#2563eb", cursor="hand2")
        email_lbl.pack(side="left")
        email_lbl.bind("<Button-1>", lambda e: webbrowser.open(f"mailto:{AUTHOR_EMAIL}"))

        ttk.Label(frame, text="  ·  ", foreground="#666").pack(side="left")

        linkedin_lbl = tk.Label(frame, text="LinkedIn", fg="#2563eb", cursor="hand2")
        linkedin_lbl.pack(side="left")
        linkedin_lbl.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_LINKEDIN))

    # -------------------------------------------------------------- logging
    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text="Activity Log")
        frame.pack(fill="both", expand=False, padx=8, pady=8)
        self.log_text = tk.Text(frame, height=8, wrap="word", state="disabled",
                                 bg="#111", fg="#ddd", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def log(self, msg):
        def _write():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _write)

    def run_async(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ----------------------------------------------------------- cleanup tab
    def _build_cleanup_tab(self):
        t = self.cleanup_tab
        ttk.Label(t, text="Temporary files & caches", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        ttk.Label(
            t, text="Scans folders first so you can see how much space will be freed."
        ).pack(anchor="w", padx=10)

        btn_frame = ttk.Frame(t)
        btn_frame.pack(anchor="w", padx=10, pady=10)
        ttk.Button(btn_frame, text="Scan", command=lambda: self.run_async(self._scan_temp)).pack(side="left")
        ttk.Button(btn_frame, text="Clean Temp Files", command=lambda: self.run_async(self._clean_temp)).pack(
            side="left", padx=6
        )
        ttk.Button(btn_frame, text="Empty Recycle Bin", command=lambda: self.run_async(self._empty_recycle)).pack(
            side="left", padx=6
        )
        ttk.Button(btn_frame, text="Clear Browser Caches", command=lambda: self.run_async(self._clean_browser_cache)).pack(
            side="left", padx=6
        )

        self.cleanup_result = tk.StringVar(value="Not scanned yet.")
        ttk.Label(t, textvariable=self.cleanup_result, foreground="#555").pack(anchor="w", padx=10)

    def _scan_temp(self):
        self.log("Scanning temp folders...")
        total = 0
        for getter in TEMP_TARGETS:
            path = getter()
            if path:
                total += folder_size(Path(path))
        self.cleanup_result.set(f"Estimated reclaimable space: {human_size(total)}")
        self.log(f"Scan complete: {human_size(total)} reclaimable.")

    def _clean_temp(self):
        self.log("Cleaning temp files...")
        freed = 0
        seen = set()
        for getter in TEMP_TARGETS:
            path = getter()
            if path and path not in seen:
                seen.add(path)
                freed += delete_folder_contents(Path(path), self.log)
        self.log(f"Freed approximately {human_size(freed)} from temp folders.")

    def _empty_recycle(self):
        if not IS_WINDOWS:
            self.log("Recycle Bin operation only available on Windows.")
            return
        empty_recycle_bin()
        self.log("Recycle Bin emptied.")

    def _clean_browser_cache(self):
        if not IS_WINDOWS:
            self.log("Browser cache cleanup only available on Windows.")
            return
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        freed = 0
        for name, getter in BROWSER_CACHE_TARGETS.items():
            path = getter(local)
            if path.exists():
                self.log(f"Clearing {name} cache...")
                freed += delete_folder_contents(path, self.log)
        self.log(f"Freed approximately {human_size(freed)} from browser caches. "
                  "Close browsers first for best results.")

    # ----------------------------------------------------------- startup tab
    def _build_startup_tab(self):
        t = self.startup_tab
        ttk.Label(t, text="Programs that launch at Windows startup", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        ttk.Label(
            t, text="Uncheck an item to disable it (safely reversible - a backup is kept)."
        ).pack(anchor="w", padx=10)

        list_frame = ttk.Frame(t)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.startup_canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.startup_canvas.yview)
        self.startup_inner = ttk.Frame(self.startup_canvas)
        self.startup_inner.bind(
            "<Configure>", lambda e: self.startup_canvas.configure(scrollregion=self.startup_canvas.bbox("all"))
        )
        self.startup_canvas.create_window((0, 0), window=self.startup_inner, anchor="nw")
        self.startup_canvas.configure(yscrollcommand=scrollbar.set)
        self.startup_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Button(t, text="Refresh List", command=self._refresh_startup).pack(anchor="w", padx=10, pady=(0, 10))
        self._refresh_startup()

    def _refresh_startup(self):
        for widget in self.startup_inner.winfo_children():
            widget.destroy()

        if not IS_WINDOWS:
            ttk.Label(self.startup_inner, text="Startup Manager only available on Windows.").pack(anchor="w")
            return

        items = list_startup_items()
        backup = load_backup()

        for item in items:
            var = tk.BooleanVar(value=True)
            row = ttk.Frame(self.startup_inner)
            row.pack(fill="x", pady=2)
            cb = ttk.Checkbutton(
                row, variable=var,
                command=lambda i=item, v=var: self._toggle_startup(i, v),
            )
            cb.pack(side="left")
            label = f"{item['name']}  ({hive_name(item['hive'])})"
            ttk.Label(row, text=label).pack(side="left", padx=4)
            path_label = ttk.Label(row, text=item["value"], foreground="#777")
            path_label.pack(side="left", padx=4)

        for key_id in backup:
            hive_str, subkey, name = key_id.split("|", 2)
            row = ttk.Frame(self.startup_inner)
            row.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(
                row, variable=var,
                command=lambda k=key_id, v=var: self._toggle_restore(k, v),
            )
            cb.pack(side="left")
            ttk.Label(row, text=f"{name}  ({hive_str})  [disabled]").pack(side="left", padx=4)

        if not items and not backup:
            ttk.Label(self.startup_inner, text="No startup items found.").pack(anchor="w")

    def _toggle_startup(self, item, var):
        if not var.get():
            self.run_async(lambda: self._disable_and_refresh(item))

    def _disable_and_refresh(self, item):
        disable_startup_item(item, self.log)
        self.after(0, self._refresh_startup)

    def _toggle_restore(self, key_id, var):
        if var.get():
            self.run_async(lambda: self._restore_and_refresh(key_id))

    def _restore_and_refresh(self, key_id):
        restore_startup_item(key_id, self.log)
        self.after(0, self._refresh_startup)

    # ------------------------------------------------------------ visual tab
    def _build_visual_tab(self):
        t = self.visual_tab
        ttk.Label(t, text="Visual effects", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        ttk.Label(
            t, text="Turning these off reduces GPU/CPU overhead - useful on older or low-spec machines."
        ).pack(anchor="w", padx=10)

        self.visual_vars = {}
        for name in VISUAL_EFFECTS:
            var = tk.BooleanVar(value=get_visual_effect(name) if IS_WINDOWS else True)
            self.visual_vars[name] = var
            ttk.Checkbutton(
                t, text=name, variable=var,
                command=lambda n=name, v=var: self.run_async(lambda: set_visual_effect(n, v.get(), self.log)),
            ).pack(anchor="w", padx=20, pady=3)

        btn_frame = ttk.Frame(t)
        btn_frame.pack(anchor="w", padx=10, pady=15)
        ttk.Button(btn_frame, text="Best Performance (turn all off)",
                   command=lambda: self.run_async(self._best_performance)).pack(side="left")
        ttk.Button(btn_frame, text="Best Appearance (turn all on)",
                   command=lambda: self.run_async(self._best_appearance)).pack(side="left", padx=6)

    def _best_performance(self):
        for name, var in self.visual_vars.items():
            var.set(False)
            set_visual_effect(name, False, self.log)

    def _best_appearance(self):
        for name, var in self.visual_vars.items():
            var.set(True)
            set_visual_effect(name, True, self.log)

    # --------------------------------------------------------- services tab
    def _build_services_tab(self):
        t = self.services_tab
        ttk.Label(t, text="Optional Windows services", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        ttk.Label(
            t, text="Only non-critical, optional services are listed. Requires admin to change."
        ).pack(anchor="w", padx=10)

        columns = ("service", "status", "description")
        self.services_tree = ttk.Treeview(t, columns=columns, show="headings", height=10)
        self.services_tree.heading("service", text="Service")
        self.services_tree.heading("status", text="Status")
        self.services_tree.heading("description", text="Description")
        self.services_tree.column("service", width=220)
        self.services_tree.column("status", width=80)
        self.services_tree.column("description", width=420)
        self.services_tree.pack(fill="both", expand=True, padx=10, pady=10)

        btn_frame = ttk.Frame(t)
        btn_frame.pack(anchor="w", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Refresh", command=lambda: self.run_async(self._refresh_services)).pack(side="left")
        ttk.Button(btn_frame, text="Stop Selected", command=lambda: self.run_async(self._stop_selected_service)).pack(
            side="left", padx=6
        )
        ttk.Button(btn_frame, text="Start Selected", command=lambda: self.run_async(self._start_selected_service)).pack(
            side="left", padx=6
        )
        ttk.Button(
            btn_frame, text="Disable at Startup",
            command=lambda: self.run_async(lambda: self._set_startup_selected("disabled")),
        ).pack(side="left", padx=6)
        ttk.Button(
            btn_frame, text="Set to Manual",
            command=lambda: self.run_async(lambda: self._set_startup_selected("demand")),
        ).pack(side="left", padx=6)
        ttk.Button(
            btn_frame, text="Set to Automatic",
            command=lambda: self.run_async(lambda: self._set_startup_selected("auto")),
        ).pack(side="left", padx=6)

        self.run_async(self._refresh_services)

    def _refresh_services(self):
        self.after(0, lambda: self.services_tree.delete(*self.services_tree.get_children()))
        for svc_name, (display, desc, _risk) in SAFE_SERVICES.items():
            status = sc_query(svc_name) if IS_WINDOWS else "N/A"
            self.after(0, lambda s=svc_name, d=display, st=status, de=desc:
                       self.services_tree.insert("", "end", iid=s, values=(d, st, de)))

    def _selected_service(self):
        sel = self.services_tree.selection()
        return sel[0] if sel else None

    def _stop_selected_service(self):
        svc = self._selected_service()
        if svc:
            sc_stop(svc, self.log)
            self._refresh_services()

    def _start_selected_service(self):
        svc = self._selected_service()
        if svc:
            sc_start(svc, self.log)
            self._refresh_services()

    def _set_startup_selected(self, mode):
        svc = self._selected_service()
        if svc:
            sc_set_startup(svc, mode, self.log)

    # --------------------------------------------------------- sysinfo tab
    def _build_sysinfo_tab(self):
        t = self.sysinfo_tab
        ttk.Label(t, text="System snapshot", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.sysinfo_text = tk.Text(t, height=18, wrap="word", state="disabled", font=("Consolas", 10))
        self.sysinfo_text.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(t, text="Refresh", command=lambda: self.run_async(self._refresh_sysinfo)).pack(
            anchor="w", padx=10, pady=(0, 10)
        )
        self.run_async(self._refresh_sysinfo)

    def _refresh_sysinfo(self):
        lines = []
        if IS_WINDOWS:
            mem = get_memory_info()
            if mem:
                lines.append(f"Memory load: {mem.dwMemoryLoad}%")
                lines.append(f"Total RAM:   {human_size(mem.ullTotalPhys)}")
                lines.append(f"Available:   {human_size(mem.ullAvailPhys)}")
                lines.append("")
            lines.append("Disks:")
            for letter, usage in get_disk_info():
                used = usage.total - usage.free
                pct = (used / usage.total * 100) if usage.total else 0
                lines.append(
                    f"  {letter}  {human_size(used)} used / {human_size(usage.total)} "
                    f"total  ({pct:.0f}% full)"
                )
            lines.append("")
            lines.append(f"CPU logical processors: {os.cpu_count()}")
        else:
            lines.append("System info only available on Windows.")

        text = "\n".join(lines)

        def _write():
            self.sysinfo_text.configure(state="normal")
            self.sysinfo_text.delete("1.0", "end")
            self.sysinfo_text.insert("1.0", text)
            self.sysinfo_text.configure(state="disabled")
        self.after(0, _write)


def main():
    if IS_WINDOWS and not is_admin():
        # Not fatal - many features still work read-only. We just warn.
        pass
    app = OptimizerApp()
    app.mainloop()

import argparse

def cli_mode():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", help="Clean temp files", action="store_true")
    parser.add_argument("--info", help="Show system info", action="store_true")

    args = parser.parse_args()

    if args.clean:
        print("Cleaning temp files...")

    if args.info:
        print("Showing system info...")


def main():
    if len(sys.argv) > 1:
        cli_mode()
    else:
        app = OptimizerApp()
        app.mainloop()


if __name__ == "__main__":
    main()
