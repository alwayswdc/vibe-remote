"""Vibe Remote Manager - Desktop GUI for managing the vibe-remote service.

Provides start/stop/restart, status display, live log viewer,
auto-start toggle, and system tray integration.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext, messagebox

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VIBE_HOME = Path(os.environ.get("VIBE_REMOTE_HOME", str(Path.home() / ".vibe_remote")))
LOG_FILE = VIBE_HOME / "logs" / "vibe_remote.log"
PID_FILE = VIBE_HOME / "runtime" / "vibe.pid"
UI_PID_FILE = VIBE_HOME / "runtime" / "vibe-ui.pid"
STATUS_FILE = VIBE_HOME / "runtime" / "status.json"
CONFIG_FILE = VIBE_HOME / "config" / "config.json"
WEB_UI_URL = "http://127.0.0.1:5123"

# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

kernel32 = ctypes.windll.kernel32


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive on Windows."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = ctypes.wintypes.DWORD()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    return exit_code.value == 259  # STILL_ACTIVE


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


def get_status() -> dict:
    """Return current vibe-remote status."""
    pid = _read_pid(PID_FILE)
    ui_pid = _read_pid(UI_PID_FILE)
    service_running = pid is not None and _pid_alive(pid)
    ui_running = ui_pid is not None and _pid_alive(ui_pid)

    uptime = None
    if service_running and STATUS_FILE.exists():
        try:
            data = json.loads(STATUS_FILE.read_text())
            started = data.get("started_at")
            if started:
                uptime = time.time() - started
        except Exception:
            pass

    return {
        "service_running": service_running,
        "ui_running": ui_running,
        "service_pid": pid if service_running else None,
        "ui_pid": ui_pid if ui_running else None,
        "uptime": uptime,
    }


def _run_vibe_cmd(*args: str) -> subprocess.CompletedProcess:
    """Run a vibe CLI command."""
    return subprocess.run(
        [sys.executable, "-m", "vibe", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def start_service() -> bool:
    """Start vibe-remote service."""
    r = _run_vibe_cmd()
    return r.returncode == 0


def stop_service() -> bool:
    """Stop vibe-remote service."""
    r = _run_vibe_cmd("stop")
    return r.returncode == 0


def restart_service() -> bool:
    """Restart vibe-remote service."""
    stop_service()
    time.sleep(1)
    return start_service()


# ---------------------------------------------------------------------------
# Auto-start (Registry Run key - no admin needed)
# ---------------------------------------------------------------------------

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_VALUE_NAME = "VibeRemote"


def _get_autostart_cmd() -> str:
    return f'"{sys.executable}" -m vibe'


def is_autostart_enabled() -> bool:
    """Check if auto-start is enabled in registry."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, _REG_VALUE_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def enable_autostart() -> bool:
    """Enable auto-start via registry Run key."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _REG_VALUE_NAME, 0, winreg.REG_SZ, _get_autostart_cmd())
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def disable_autostart() -> bool:
    """Disable auto-start by removing registry value."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _REG_VALUE_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class VibeManagerApp:
    """Main application window."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Vibe Remote Manager")
        self.root.geometry("640x520")
        self.root.minsize(500, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._log_thread: threading.Thread | None = None
        self._log_stop = threading.Event()
        self._status_after_id = None

        self._build_ui()
        self._start_status_polling()
        self._start_log_tail()

    # -- UI construction --

    def _build_ui(self):
        # Top: status frame
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=8)
        status_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._status_label = ttk.Label(status_frame, text="Checking...", font=("", 11))
        self._status_label.pack(side="left")

        self._pid_label = ttk.Label(status_frame, text="", font=("", 9))
        self._pid_label.pack(side="right")

        # Buttons
        btn_frame = ttk.Frame(self.root, padding=4)
        btn_frame.pack(fill="x", padx=8)

        self._btn_start = ttk.Button(btn_frame, text="▶ Start", width=10, command=self._cmd_start)
        self._btn_start.pack(side="left", padx=2)

        self._btn_stop = ttk.Button(btn_frame, text="■ Stop", width=10, command=self._cmd_stop)
        self._btn_stop.pack(side="left", padx=2)

        self._btn_restart = ttk.Button(btn_frame, text="↻ Restart", width=10, command=self._cmd_restart)
        self._btn_restart.pack(side="left", padx=2)

        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)

        self._btn_webui = ttk.Button(btn_frame, text="Web UI", width=10, command=self._cmd_webui)
        self._btn_webui.pack(side="left", padx=2)

        self._btn_config = ttk.Button(btn_frame, text="Config", width=10, command=self._cmd_config)
        self._btn_config.pack(side="left", padx=2)

        self._btn_folder = ttk.Button(btn_frame, text="Data Folder", width=10, command=self._cmd_folder)
        self._btn_folder.pack(side="left", padx=2)

        # Auto-start checkbox
        auto_frame = ttk.Frame(self.root, padding=4)
        auto_frame.pack(fill="x", padx=8)

        self._autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        self._autostart_cb = ttk.Checkbutton(
            auto_frame,
            text="Auto-start on login",
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        self._autostart_cb.pack(side="left")

        # Log viewer
        log_frame = ttk.LabelFrame(self.root, text="Logs", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", font=("Consolas", 9), state="disabled",
        )
        self._log_text.pack(fill="both", expand=True)

    # -- Status polling --

    def _update_status(self):
        try:
            s = get_status()
        except Exception:
            self._status_label.config(text="Error checking status", foreground="orange")
            return

        if s["service_running"]:
            uptime_str = ""
            if s["uptime"] is not None:
                h, rem = divmod(int(s["uptime"]), 3600)
                m, sec = divmod(rem, 60)
                uptime_str = f"  (uptime {h}h {m}m {sec}s)"
            self._status_label.config(text=f"● Running{uptime_str}", foreground="green")
            self._pid_label.config(text=f"PID: {s['service_pid']}")
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
            self._btn_restart.config(state="normal")
        else:
            self._status_label.config(text="● Stopped", foreground="red")
            self._pid_label.config(text="")
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")
            self._btn_restart.config(state="disabled")

    def _start_status_polling(self):
        self._update_status()
        self._status_after_id = self.root.after(3000, self._poll_status)

    def _poll_status(self):
        self._update_status()
        self._status_after_id = self.root.after(3000, self._poll_status)

    # -- Log tailing --

    def _start_log_tail(self):
        self._log_thread = threading.Thread(target=self._log_tail_worker, daemon=True)
        self._log_thread.start()

    def _log_tail_worker(self):
        """Background thread that tails the log file."""
        last_size = 0
        last_pos = 0

        # Start from the last 50 lines
        try:
            if LOG_FILE.exists():
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    for line in lines[-50:]:
                        self._append_log(line.rstrip())
                    last_pos = f.tell()
                    last_size = last_pos
        except Exception:
            pass

        while not self._log_stop.is_set():
            try:
                if not LOG_FILE.exists():
                    self._log_stop.wait(2)
                    continue

                size = LOG_FILE.stat().st_size
                if size < last_size:
                    last_pos = 0
                    last_size = 0

                if size > last_pos:
                    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        new_data = f.read()
                        last_pos = f.tell()
                    last_size = size
                    for line in new_data.splitlines():
                        self._append_log(line)
            except Exception:
                pass

            self._log_stop.wait(2)

    def _append_log(self, line: str):
        """Thread-safe append to log text widget."""
        self.root.after(0, self._do_append_log, line)

    def _do_append_log(self, line: str):
        self._log_text.config(state="normal")
        self._log_text.insert("end", line + "\n")
        self._log_text.see("end")
        line_count = int(self._log_text.index("end-1c").split(".")[0])
        if line_count > 1000:
            self._log_text.delete("1.0", f"{line_count - 1000}.0")
        self._log_text.config(state="disabled")

    # -- Commands --

    def _cmd_start(self):
        self._status_label.config(text="Starting...", foreground="orange")
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self):
        ok = start_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("Error", "Failed to start vibe-remote"))

    def _cmd_stop(self):
        self._status_label.config(text="Stopping...", foreground="orange")
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        ok = stop_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("Error", "Failed to stop vibe-remote"))

    def _cmd_restart(self):
        self._status_label.config(text="Restarting...", foreground="orange")
        threading.Thread(target=self._do_restart, daemon=True).start()

    def _do_restart(self):
        ok = restart_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("Error", "Failed to restart vibe-remote"))

    def _cmd_webui(self):
        os.startfile(WEB_UI_URL)

    def _cmd_config(self):
        path = CONFIG_FILE if CONFIG_FILE.exists() else VIBE_HOME / "config"
        os.startfile(str(path))

    def _cmd_folder(self):
        os.startfile(str(VIBE_HOME))

    def _toggle_autostart(self):
        if self._autostart_var.get():
            ok = enable_autostart()
            if not ok:
                self._autostart_var.set(False)
                messagebox.showerror("Error", "Failed to enable auto-start.")
        else:
            ok = disable_autostart()
            if not ok:
                self._autostart_var.set(True)
                messagebox.showerror("Error", "Failed to disable auto-start.")

    # -- Lifecycle --

    def _on_close(self):
        self._log_stop.set()
        if self._status_after_id:
            self.root.after_cancel(self._status_after_id)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        app = VibeManagerApp()
        app.run()
    except Exception as e:
        # .pyw has no console, show errors in a dialog
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Vibe Remote Manager Error", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()