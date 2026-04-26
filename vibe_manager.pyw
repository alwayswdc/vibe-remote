"""Vibe Remote 管理工具 - 桌面 GUI，管理 vibe-remote 服务。

功能：启动/停止/重启、状态显示、实时日志、开机自启动、快捷入口。
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
# 路径
# ---------------------------------------------------------------------------

VIBE_HOME = Path(os.environ.get("VIBE_REMOTE_HOME", str(Path.home() / ".vibe_remote")))
LOG_FILE = VIBE_HOME / "logs" / "vibe_remote.log"
PID_FILE = VIBE_HOME / "runtime" / "vibe.pid"
UI_PID_FILE = VIBE_HOME / "runtime" / "vibe-ui.pid"
STATUS_FILE = VIBE_HOME / "runtime" / "status.json"
CONFIG_FILE = VIBE_HOME / "config" / "config.json"
WEB_UI_URL = "http://127.0.0.1:5123"
ICON_FILE = Path(__file__).resolve().parent / "vibe_remote.ico"

# ---------------------------------------------------------------------------
# 进程管理
# ---------------------------------------------------------------------------

kernel32 = ctypes.windll.kernel32


def _pid_alive(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = ctypes.wintypes.DWORD()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    return exit_code.value == 259


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


def get_status() -> dict:
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
    return subprocess.run(
        [sys.executable, "-m", "vibe", *args],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def start_service() -> bool:
    r = _run_vibe_cmd()
    return r.returncode == 0


def stop_service() -> bool:
    r = _run_vibe_cmd("stop")
    return r.returncode == 0


def restart_service() -> bool:
    stop_service()
    time.sleep(1)
    return start_service()


# ---------------------------------------------------------------------------
# 开机自启动（注册表 Run 键，无需管理员）
# ---------------------------------------------------------------------------

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_VALUE_NAME = "VibeRemote"


def _get_autostart_cmd() -> str:
    pythonw = str(Path(sys.executable).parent / "pythonw.exe")
    return f'"{pythonw}" -m vibe'


def is_autostart_enabled() -> bool:
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
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _REG_VALUE_NAME, 0, winreg.REG_SZ, _get_autostart_cmd())
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def disable_autostart() -> bool:
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
# GUI 应用
# ---------------------------------------------------------------------------

class VibeManagerApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Vibe Remote 管理工具")
        self.root.geometry("680x560")
        self.root.minsize(560, 440)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 设置窗口图标
        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except Exception:
                pass

        self._log_thread: threading.Thread | None = None
        self._log_stop = threading.Event()
        self._status_after_id = None

        self._build_ui()
        self._start_status_polling()
        self._start_log_tail()

    def _build_ui(self):
        # ---- 状态栏 ----
        status_frame = ttk.LabelFrame(self.root, text="服务状态", padding=10)
        status_frame.pack(fill="x", padx=12, pady=(12, 4))

        self._status_label = ttk.Label(status_frame, text="检测中...", font=("", 13, "bold"))
        self._status_label.pack(side="left")

        self._pid_label = ttk.Label(status_frame, text="", font=("", 10))
        self._pid_label.pack(side="right")

        # ---- 控制按钮 ----
        btn_frame = ttk.Frame(self.root, padding=6)
        btn_frame.pack(fill="x", padx=12)

        self._btn_start = ttk.Button(btn_frame, text="▶ 启动", width=12, command=self._cmd_start)
        self._btn_start.pack(side="left", padx=3)

        self._btn_stop = ttk.Button(btn_frame, text="■ 停止", width=12, command=self._cmd_stop)
        self._btn_stop.pack(side="left", padx=3)

        self._btn_restart = ttk.Button(btn_frame, text="↻ 重启", width=12, command=self._cmd_restart)
        self._btn_restart.pack(side="left", padx=3)

        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=10)

        self._btn_webui = ttk.Button(btn_frame, text="🌐 网页管理", width=12, command=self._cmd_webui)
        self._btn_webui.pack(side="left", padx=3)

        self._btn_config = ttk.Button(btn_frame, text="⚙ 配置", width=12, command=self._cmd_config)
        self._btn_config.pack(side="left", padx=3)

        self._btn_folder = ttk.Button(btn_frame, text="📁 数据目录", width=12, command=self._cmd_folder)
        self._btn_folder.pack(side="left", padx=3)

        # ---- 开机自启动 ----
        auto_frame = ttk.Frame(self.root, padding=6)
        auto_frame.pack(fill="x", padx=12)

        self._autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        self._autostart_cb = ttk.Checkbutton(
            auto_frame,
            text="开机自动启动",
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        self._autostart_cb.pack(side="left")

        # ---- 日志查看 ----
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=4)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", font=("Consolas", 9), state="disabled",
            background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        self._log_text.pack(fill="both", expand=True)

    # -- 状态轮询 --

    def _update_status(self):
        try:
            s = get_status()
        except Exception:
            self._status_label.config(text="状态检测异常", foreground="orange")
            return

        if s["service_running"]:
            uptime_str = ""
            if s["uptime"] is not None:
                h, rem = divmod(int(s["uptime"]), 3600)
                m, sec = divmod(rem, 60)
                uptime_str = f"  (运行 {h}时{m}分{sec}秒)"
            self._status_label.config(text=f"● 运行中{uptime_str}", foreground="green")
            self._pid_label.config(text=f"PID: {s['service_pid']}")
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
            self._btn_restart.config(state="normal")
        else:
            self._status_label.config(text="● 已停止", foreground="red")
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

    # -- 日志追踪 --

    def _start_log_tail(self):
        self._log_thread = threading.Thread(target=self._log_tail_worker, daemon=True)
        self._log_thread.start()

    def _log_tail_worker(self):
        last_size = 0
        last_pos = 0
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
        self.root.after(0, self._do_append_log, line)

    def _do_append_log(self, line: str):
        self._log_text.config(state="normal")
        self._log_text.insert("end", line + "\n")
        self._log_text.see("end")
        line_count = int(self._log_text.index("end-1c").split(".")[0])
        if line_count > 1000:
            self._log_text.delete("1.0", f"{line_count - 1000}.0")
        self._log_text.config(state="disabled")

    # -- 命令 --

    def _cmd_start(self):
        self._status_label.config(text="正在启动...", foreground="orange")
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self):
        ok = start_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("错误", "启动失败"))

    def _cmd_stop(self):
        self._status_label.config(text="正在停止...", foreground="orange")
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        ok = stop_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("错误", "停止失败"))

    def _cmd_restart(self):
        self._status_label.config(text="正在重启...", foreground="orange")
        threading.Thread(target=self._do_restart, daemon=True).start()

    def _do_restart(self):
        ok = restart_service()
        self.root.after(0, self._update_status)
        if not ok:
            self.root.after(0, lambda: messagebox.showerror("错误", "重启失败"))

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
                messagebox.showerror("错误", "启用开机自启动失败")
        else:
            ok = disable_autostart()
            if not ok:
                self._autostart_var.set(True)
                messagebox.showerror("错误", "禁用开机自启动失败")

    # -- 生命周期 --

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
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Vibe Remote 管理工具错误", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()