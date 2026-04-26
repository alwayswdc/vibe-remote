#!/usr/bin/env python3
"""Vibe Remote 桌面管理器 - 可视化管理 Vibe Remote 服务"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

# ── Paths ──────────────────────────────────────────────────────────────────
VIBE_HOME = Path(os.environ.get("VIBE_REMOTE_HOME", Path.home() / ".vibe_remote"))
CONFIG_PATH = VIBE_HOME / "config" / "config.json"
SETTINGS_PATH = VIBE_HOME / "state" / "settings.json"
SESSIONS_PATH = VIBE_HOME / "state" / "sessions.json"
LOG_PATH = VIBE_HOME / "logs" / "vibe_remote.log"
PID_PATH = VIBE_HOME / "runtime" / "vibe.pid"
UI_PID_PATH = VIBE_HOME / "runtime" / "ui.pid"
STATUS_PATH = VIBE_HOME / "runtime" / "status.json"
DOCTOR_PATH = VIBE_HOME / "runtime" / "doctor.json"
SERVICE_STDOUT = VIBE_HOME / "runtime" / "service_stdout.log"
SERVICE_STDERR = VIBE_HOME / "runtime" / "service_stderr.log"
UI_STDOUT = VIBE_HOME / "runtime" / "ui_stdout.log"
UI_STDERR = VIBE_HOME / "runtime" / "ui_stderr.log"
VIBE_BIN = Path.home() / ".local" / "bin" / "vibe"

# ── Log level colors ──────────────────────────────────────────────────────
LOG_COLORS = {
    "DEBUG": "#6c7086",
    "INFO": "#89b4fa",
    "WARNING": "#f9e2af",
    "ERROR": "#f38ba8",
    "CRITICAL": "#f38ba8",
}


# ── Helpers ────────────────────────────────────────────────────────────────
def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "超时", -1
    except FileNotFoundError:
        return f"命令不存在: {cmd[0]}", -1


def get_service_pid():
    if PID_PATH.exists():
        try:
            return int(PID_PATH.read_text().strip())
        except ValueError:
            pass
    return 0


def get_ui_pid():
    if UI_PID_PATH.exists():
        try:
            return int(UI_PID_PATH.read_text().strip())
        except ValueError:
            pass
    status = read_json(STATUS_PATH)
    if status and "ui_pid" in status:
        try:
            return int(status["ui_pid"])
        except (ValueError, TypeError):
            pass
    return 0


def get_service_status():
    pid = get_service_pid()
    ui_pid = get_ui_pid()
    service_alive = pid_alive(pid) if pid else False
    ui_alive = pid_alive(ui_pid) if ui_pid else False
    return {
        "service_pid": pid,
        "ui_pid": ui_pid,
        "service_alive": service_alive,
        "ui_alive": ui_alive,
        "running": service_alive,
    }


def get_config():
    return read_json(CONFIG_PATH) or {}


def save_config(cfg):
    write_json(CONFIG_PATH, cfg)


def get_settings():
    return read_json(SETTINGS_PATH) or {}


def get_sessions():
    return read_json(SESSIONS_PATH) or {}


def get_doctor():
    return read_json(DOCTOR_PATH) or {}


def get_log_lines(n=200):
    if not LOG_PATH.exists():
        return ["日志文件不存在"]
    try:
        lines = LOG_PATH.read_text("utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception as e:
        return [f"读取日志失败: {e}"]


def get_runtime_log(path: Path, n=100):
    if not path.exists():
        return ["文件不存在"]
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception as e:
        return [f"读取失败: {e}"]


def get_uptime_str(pid: int) -> str:
    if not pid or not pid_alive(pid):
        return "-"
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "etimes="],
                           capture_output=True, text=True, timeout=3)
        secs = int(r.stdout.strip())
        if secs < 60:
            return f"{secs}秒"
        elif secs < 3600:
            return f"{secs // 60}分{secs % 60}秒"
        else:
            h, m = divmod(secs // 60, 60)
            return f"{h}时{m}分"
    except Exception:
        return "-"


# ── Main Application ──────────────────────────────────────────────────────
class VibeRemoteManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Vibe Remote 管理")
        self.geometry("820x640")
        self.resizable(True, True)
        self._auto_refresh = True

        # Style
        style = ttk.Style(self)
        style.configure("Run.TLabel", foreground="#16a34a", font=("", 11, "bold"))
        style.configure("Stop.TLabel", foreground="#dc2626", font=("", 11, "bold"))
        style.configure("Unknown.TLabel", foreground="#9ca3af", font=("", 11, "bold"))
        style.configure("Card.TLabelframe.Label", font=("", 10, "bold"))

        # ── Top: Service Control ──────────────────────────────────────────
        top = ttk.LabelFrame(self, text="服务控制", padding=8)
        top.pack(fill="x", padx=10, pady=(10, 4))

        self.status_var = tk.StringVar(value="状态: 检查中...")
        self.status_label = ttk.Label(top, textvariable=self.status_var, style="Unknown.TLabel")
        self.status_label.pack(side="left", padx=5)

        self.pid_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.pid_var, font=("", 9), foreground="#6b7280").pack(side="left", padx=10)

        self.uptime_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.uptime_var, font=("", 9), foreground="#6b7280").pack(side="left", padx=5)

        btn_frame = ttk.Frame(top)
        btn_frame.pack(side="right")
        ttk.Button(btn_frame, text="启动", command=self.start_service, width=8).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="重启", command=self.restart_service, width=8).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="停止", command=self.stop_service, width=8).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="刷新", command=self.refresh, width=8).pack(side="right", padx=2)

        # ── Middle: Notebook ──────────────────────────────────────────────
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=4)

        self._build_overview_tab()
        self._build_agents_tab()
        self._build_platforms_tab()
        self._build_sessions_tab()
        self._build_logs_tab()
        self._build_config_tab()
        self._build_diagnostic_tab()

        # ── Bottom: Quick actions ─────────────────────────────────────────
        bot = ttk.Frame(self, padding=6)
        bot.pack(fill="x", padx=10, pady=(4, 10))

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bot, text="自动刷新", variable=self.auto_var, command=self._toggle_auto).pack(side="left")
        ttk.Label(bot, text="  |  ", foreground="#d1d5db").pack(side="left")

        ttk.Button(bot, text="打开 Web UI", command=self.open_web_ui).pack(side="left", padx=4)
        ttk.Button(bot, text="开机自启", command=self.toggle_autostart).pack(side="left", padx=4)
        ttk.Button(bot, text="运行诊断", command=self.run_doctor).pack(side="left", padx=4)
        ttk.Button(bot, text="升级", command=self.upgrade).pack(side="left", padx=4)

        # Initial refresh
        self.refresh()
        self._schedule_auto_refresh()

    # ── Tab builders ──────────────────────────────────────────────────────

    def _build_overview_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="概览")

        # Status cards
        cards = ttk.Frame(frame)
        cards.pack(fill="x", pady=(0, 10))

        self.svc_card = self._status_card(cards, "主服务", "#6b7280")
        self.svc_card.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.ui_card = self._status_card(cards, "Web UI", "#6b7280")
        self.ui_card.pack(side="left", fill="both", expand=True, padx=(5, 5))

        self.agent_card = self._status_card(cards, "Agent", "#6b7280")
        self.agent_card.pack(side="left", fill="both", expand=True, padx=(5, 0))

        # Info section
        info = ttk.LabelFrame(frame, text="服务信息", padding=8)
        info.pack(fill="both", expand=True)

        self.info_text = tk.Text(info, wrap="word", font=("monospace", 10), height=12, state="disabled",
                                 bg="#f9fafb", relief="flat")
        self.info_text.pack(fill="both", expand=True)

    def _status_card(self, parent, title, color):
        card = ttk.LabelFrame(parent, text=title, padding=8, style="Card.TLabelframe")
        var = tk.StringVar(value="未知")
        lbl = ttk.Label(card, textvariable=var, font=("", 13, "bold"), foreground=color)
        lbl.pack()
        card._var = var
        card._label = lbl
        return card

    def _build_agents_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Agent 管理")

        # Agent status table
        cols = ("name", "enabled", "cli_path", "status", "version", "default")
        self.agent_tree = ttk.Treeview(frame, columns=cols, show="headings", height=6)
        self.agent_tree.heading("name", text="Agent")
        self.agent_tree.heading("enabled", text="启用")
        self.agent_tree.heading("cli_path", text="CLI 路径")
        self.agent_tree.heading("status", text="状态")
        self.agent_tree.heading("version", text="版本")
        self.agent_tree.heading("default", text="默认")
        self.agent_tree.column("name", width=100)
        self.agent_tree.column("enabled", width=50)
        self.agent_tree.column("cli_path", width=220)
        self.agent_tree.column("status", width=70)
        self.agent_tree.column("version", width=100)
        self.agent_tree.column("default", width=50)
        self.agent_tree.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="检测 Agent", command=self.detect_agents).pack(side="left", padx=4)
        ttk.Button(btns, text="设为默认", command=self.set_default_agent).pack(side="left", padx=4)
        ttk.Button(btns, text="编辑配置", command=self.edit_agent_config).pack(side="left", padx=4)
        ttk.Button(btns, text="启用/禁用", command=self.toggle_agent).pack(side="left", padx=4)

    def _build_platforms_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="IM 平台")

        cols = ("platform", "configured", "status", "channels")
        self.platform_tree = ttk.Treeview(frame, columns=cols, show="headings", height=6)
        self.platform_tree.heading("platform", text="平台")
        self.platform_tree.heading("configured", text="已配置")
        self.platform_tree.heading("status", text="状态")
        self.platform_tree.heading("channels", text="频道数")
        self.platform_tree.column("platform", width=100)
        self.platform_tree.column("configured", width=70)
        self.platform_tree.column("status", width=100)
        self.platform_tree.column("channels", width=80)
        self.platform_tree.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="测试连接", command=self.test_platform).pack(side="left", padx=4)
        ttk.Button(btns, text="编辑平台配置", command=self.edit_platform_config).pack(side="left", padx=4)

    def _build_sessions_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="会话")

        cols = ("session_key", "agent", "model", "thread_id", "created", "messages")
        self.session_tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        self.session_tree.heading("session_key", text="会话标识")
        self.session_tree.heading("agent", text="Agent")
        self.session_tree.heading("model", text="模型")
        self.session_tree.heading("thread_id", text="线程ID")
        self.session_tree.heading("created", text="创建时间")
        self.session_tree.heading("messages", text="消息数")
        self.session_tree.column("session_key", width=200)
        self.session_tree.column("agent", width=80)
        self.session_tree.column("model", width=120)
        self.session_tree.column("thread_id", width=120)
        self.session_tree.column("created", width=150)
        self.session_tree.column("messages", width=60)
        self.session_tree.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="刷新", command=self._refresh_sessions).pack(side="left", padx=4)
        ttk.Button(btns, text="清理过期", command=self._cleanup_sessions).pack(side="left", padx=4)

    def _build_logs_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="日志")

        # Log source selector
        sel = ttk.Frame(frame)
        sel.pack(fill="x", pady=(0, 4))
        ttk.Label(sel, text="日志来源:").pack(side="left")
        self.log_source = tk.StringVar(value="main")
        sources = [("主日志", "main"), ("服务输出", "svc_out"), ("服务错误", "svc_err"),
                   ("UI输出", "ui_out"), ("UI错误", "ui_err")]
        for text, val in sources:
            ttk.Radiobutton(sel, text=text, variable=self.log_source, value=val,
                            command=self._refresh_logs).pack(side="left", padx=6)

        self.log_auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sel, text="自动滚动", variable=self.log_auto_var).pack(side="right")

        ttk.Button(sel, text="刷新", command=self._refresh_logs).pack(side="right", padx=4)
        ttk.Button(sel, text="清空显示", command=lambda: self.log_text.delete("1.0", "end")).pack(side="right", padx=4)
        ttk.Button(sel, text="导出日志", command=self._export_log).pack(side="right", padx=4)

        # Log filter
        filt = ttk.Frame(frame)
        filt.pack(fill="x", pady=(0, 4))
        ttk.Label(filt, text="过滤:").pack(side="left")
        self.log_filter = tk.StringVar()
        self.log_filter.trace_add("write", lambda *_: self._refresh_logs())
        ttk.Entry(filt, textvariable=self.log_filter, width=30).pack(side="left", padx=4)

        # Log level filter
        ttk.Label(filt, text="级别:").pack(side="left", padx=(10, 0))
        self.log_level_var = tk.StringVar(value="ALL")
        level_cb = ttk.Combobox(filt, textvariable=self.log_level_var,
                                values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR"],
                                state="readonly", width=8)
        level_cb.pack(side="left", padx=4)
        level_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_logs())

        # Log text with scrollbars
        log_container = ttk.Frame(frame)
        log_container.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_container, wrap="none", font=("monospace", 9), state="disabled",
                                bg="#1e1e2e", fg="#cdd6f4", insertbackground="white")
        log_scroll_y = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll_y.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll_y.pack(side="right", fill="y")

        # Configure log level tags for coloring
        for level, color in LOG_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)
        self.log_text.tag_configure("other", foreground="#cdd6f4")

    def _build_config_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="配置")

        # Config sections
        paned = ttk.PanedWindow(frame, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # Left: config tree
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="配置项", font=("", 10, "bold")).pack(anchor="w")
        self.config_tree = ttk.Treeview(left, show="tree", height=20)
        self.config_tree.pack(fill="both", expand=True, pady=(4, 0))
        self.config_tree.bind("<<TreeviewSelect>>", self._on_config_select)

        # Right: config detail
        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        ttk.Label(right, text="配置内容 (JSON)", font=("", 10, "bold")).pack(anchor="w")
        self.config_text = tk.Text(right, wrap="word", font=("monospace", 10), height=20,
                                   bg="#f9fafb", relief="flat")
        self.config_text.pack(fill="both", expand=True, pady=(4, 0))

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="保存配置", command=self._save_config_from_text).pack(side="left", padx=4)
        ttk.Button(btns, text="重载", command=self._load_config_tree).pack(side="left", padx=4)
        ttk.Button(btns, text="用编辑器打开", command=self._open_config_editor).pack(side="left", padx=4)
        ttk.Button(btns, text="重置为默认", command=self._reset_config).pack(side="left", padx=4)

        self._load_config_tree()

    def _build_diagnostic_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="诊断")

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="运行诊断", command=self.run_doctor).pack(side="left", padx=4)
        ttk.Button(btns, text="刷新", command=self._refresh_diagnostic).pack(side="left", padx=4)
        ttk.Button(btns, text="检查更新", command=self._check_update).pack(side="left", padx=4)

        self.diag_text = tk.Text(frame, wrap="word", font=("monospace", 10), state="disabled",
                                 bg="#f9fafb", relief="flat")
        self.diag_text.pack(fill="both", expand=True)

    # ── Service actions ───────────────────────────────────────────────────

    def start_service(self):
        out, rc = run_cmd([str(VIBE_BIN)])
        if rc == 0:
            self.after(2000, self.refresh)
        else:
            messagebox.showerror("启动失败", f"启动服务失败:\n{out}")

    def stop_service(self):
        out, rc = run_cmd([str(VIBE_BIN), "stop"])
        if rc == 0:
            self.after(1000, self.refresh)
        else:
            messagebox.showerror("停止失败", f"停止服务失败:\n{out}")

    def restart_service(self):
        out, rc = run_cmd([str(VIBE_BIN), "stop"])
        time.sleep(1)
        out2, rc2 = run_cmd([str(VIBE_BIN)])
        if rc2 == 0:
            self.after(2000, self.refresh)
        else:
            messagebox.showerror("重启失败", f"重启服务失败:\n{out2}")

    def open_web_ui(self):
        cfg = get_config()
        host = "127.0.0.1"
        port = 5123
        if cfg:
            ui_cfg = cfg.get("ui", {})
            host = ui_cfg.get("setup_host", host)
            port = ui_cfg.get("setup_port", port)
        url = f"http://{host}:{port}"
        subprocess.Popen(["xdg-open", url], start_new_session=True)

    def toggle_autostart(self):
        svc_path = Path.home() / ".config/systemd/user/vibe-remote.service"
        if svc_path.exists():
            out, rc = run_cmd(["systemctl", "--user", "is-enabled", "vibe-remote.service"])
            if rc == 0:
                run_cmd(["systemctl", "--user", "disable", "vibe-remote.service"])
                messagebox.showinfo("开机自启", "已关闭开机自启动")
            else:
                run_cmd(["systemctl", "--user", "enable", "vibe-remote.service"])
                messagebox.showinfo("开机自启", "已开启开机自启动")
        else:
            messagebox.showwarning("开机自启", "systemd 服务文件不存在，请先创建")

    def run_doctor(self):
        out, rc = run_cmd([str(VIBE_BIN), "doctor"], timeout=30)
        self._refresh_diagnostic()

    def upgrade(self):
        if not messagebox.askyesno("升级", "确定要升级 Vibe Remote 到最新版本吗？"):
            return
        out, rc = run_cmd([str(VIBE_BIN), "upgrade"], timeout=60)
        if rc == 0:
            messagebox.showinfo("升级", f"升级成功:\n{out}")
            self.refresh()
        else:
            messagebox.showerror("升级失败", f"升级失败:\n{out}")

    def _check_update(self):
        out, rc = run_cmd([str(VIBE_BIN), "check-update"], timeout=15)
        messagebox.showinfo("更新检查", out or "检查完成")

    # ── Agent actions ─────────────────────────────────────────────────────

    def detect_agents(self):
        cfg = get_config()
        agents_cfg = cfg.get("agents", {})
        agents_info = [
            ("Claude Code", "claude", agents_cfg.get("claude", {})),
            ("Codex", "codex", agents_cfg.get("codex", {})),
            ("OpenCode", "opencode", agents_cfg.get("opencode", {})),
        ]
        for name, key, acfg in agents_info:
            cli_path = acfg.get("cli_path", key)
            out, rc = run_cmd(["which", cli_path])
            if rc == 0:
                acfg["enabled"] = True
                acfg["cli_path"] = out
            else:
                acfg["enabled"] = False
        cfg["agents"] = agents_cfg
        save_config(cfg)
        self.refresh()

    def set_default_agent(self):
        sel = self.agent_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个 Agent")
            return
        item = self.agent_tree.item(sel[0])
        name = item["values"][0]
        agent_keys = {"Claude Code": "claude", "Codex": "codex", "OpenCode": "opencode"}
        key = agent_keys.get(name)
        if not key:
            return
        cfg = get_config()
        if "agents" not in cfg:
            cfg["agents"] = {}
        cfg["agents"]["default_backend"] = key
        save_config(cfg)
        self.refresh()

    def toggle_agent(self):
        sel = self.agent_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个 Agent")
            return
        item = self.agent_tree.item(sel[0])
        name = item["values"][0]
        agent_keys = {"Claude Code": "claude", "Codex": "codex", "OpenCode": "opencode"}
        key = agent_keys.get(name)
        if not key:
            return
        cfg = get_config()
        agents_cfg = cfg.setdefault("agents", {})
        acfg = agents_cfg.setdefault(key, {})
        acfg["enabled"] = not acfg.get("enabled", False)
        save_config(cfg)
        self.refresh()

    def edit_agent_config(self):
        cfg = get_config()
        agents_cfg = cfg.get("agents", {})
        win = AgentConfigDialog(self, agents_cfg)
        self.wait_window(win)
        if win.result:
            cfg["agents"] = win.result
            save_config(cfg)
            self.refresh()

    # ── Platform actions ──────────────────────────────────────────────────

    def test_platform(self):
        sel = self.platform_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个平台")
            return
        item = self.platform_tree.item(sel[0])
        platform = item["values"][0]
        cfg = get_config()
        platform_lower = str(platform).lower()

        if platform_lower == "slack":
            slack_cfg = cfg.get("slack", {})
            token = slack_cfg.get("bot_token", "")
            if not token:
                messagebox.showwarning("提示", "Slack bot_token 未配置")
                return
            out, rc = run_cmd([str(VIBE_BIN), "doctor"], timeout=15)
            messagebox.showinfo("Slack 测试", f"诊断结果:\n{out}")
        elif platform_lower == "discord":
            messagebox.showinfo("Discord", "请通过 Web UI 测试 Discord 连接")
        elif platform_lower == "telegram":
            messagebox.showinfo("Telegram", "请通过 Web UI 测试 Telegram 连接")
        else:
            messagebox.showinfo(platform, f"请通过 Web UI 测试 {platform} 连接")

    def edit_platform_config(self):
        cfg = get_config()
        win = PlatformConfigDialog(self, cfg)
        self.wait_window(win)
        if win.result:
            save_config(win.result)
            self.refresh()

    # ── Session actions ───────────────────────────────────────────────────

    def _refresh_sessions(self):
        self.session_tree.delete(*self.session_tree.get_children())
        sessions = get_sessions()
        settings = get_settings()

        # Sessions can be nested in various ways; try to display them
        if isinstance(sessions, dict):
            for key, val in sessions.items():
                if isinstance(val, dict):
                    agent = val.get("agent_backend", val.get("agent", ""))
                    model = val.get("model", "")
                    thread_id = val.get("thread_id", val.get("thread_ts", ""))
                    created = val.get("created_at", val.get("started_at", ""))
                    msgs = val.get("message_count", val.get("turn_count", ""))
                    self.session_tree.insert("", "end", values=(key, agent, model, thread_id, created, msgs))
                else:
                    self.session_tree.insert("", "end", values=(key, "", "", "", "", ""))

    def _cleanup_sessions(self):
        if not messagebox.askyesno("确认", "确定要清理过期会话吗？"):
            return
        # Restart service to trigger idle cleanup
        self.restart_service()

    # ── Log actions ───────────────────────────────────────────────────────

    def _export_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            title="导出日志"
        )
        if not path:
            return
        content = self.log_text.get("1.0", "end")
        with open(path, "w") as f:
            f.write(content)
        messagebox.showinfo("导出成功", f"日志已导出到: {path}")

    # ── Refresh logic ─────────────────────────────────────────────────────

    def refresh(self):
        status = get_service_status()
        cfg = get_config()

        # Status bar
        if status["running"]:
            self.status_var.set("状态: 运行中")
            self.status_label.configure(style="Run.TLabel")
        else:
            self.status_var.set("状态: 已停止")
            self.status_label.configure(style="Stop.TLabel")

        pids = []
        if status["service_pid"]:
            pids.append(f"Service PID: {status['service_pid']}")
        if status["ui_pid"]:
            pids.append(f"UI PID: {status['ui_pid']}")
        self.pid_var.set("  |  ".join(pids))

        # Uptime
        uptime = get_uptime_str(status["service_pid"])
        self.uptime_var.set(f"运行时间: {uptime}" if uptime != "-" else "")

        # Overview cards
        self._update_card(self.svc_card, "运行中" if status["service_alive"] else "已停止",
                          "#16a34a" if status["service_alive"] else "#dc2626")
        self._update_card(self.ui_card, "运行中" if status["ui_alive"] else "已停止",
                          "#16a34a" if status["ui_alive"] else "#dc2626")

        agents_cfg = cfg.get("agents", {})
        default = agents_cfg.get("default_backend", "未设置")
        self._update_card(self.agent_card, f"默认: {default}", "#6366f1")

        # Info text
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        info_lines = [
            f"Vibe Remote 版本: {self._get_version()}",
            f"配置文件: {CONFIG_PATH}",
            f"日志文件: {LOG_PATH}",
            f"默认 Agent: {default}",
            f"默认工作目录: {cfg.get('runtime', {}).get('default_cwd', '~/work')}",
            f"日志级别: {cfg.get('runtime', {}).get('log_level', 'INFO')}",
            f"Web UI: http://{cfg.get('ui', {}).get('setup_host', '127.0.0.1')}:{cfg.get('ui', {}).get('setup_port', 5123)}",
            f"语言: {cfg.get('language', 'en')}",
            f"确认模式: {cfg.get('ack_mode', 'typing')}",
            f"自动更新: {'是' if cfg.get('update', {}).get('auto_update', True) else '否'}",
            "",
            "已启用平台: " + ", ".join(cfg.get("platforms", {}).get("enabled", [])),
        ]
        self.info_text.insert("1.0", "\n".join(info_lines))
        self.info_text.config(state="disabled")

        # Agent tree
        self.agent_tree.delete(*self.agent_tree.get_children())
        agent_list = [
            ("Claude Code", "claude", agents_cfg.get("claude", {})),
            ("Codex", "codex", agents_cfg.get("codex", {})),
            ("OpenCode", "opencode", agents_cfg.get("opencode", {})),
        ]
        for name, key, acfg in agent_list:
            enabled = "是" if acfg.get("enabled", False) else "否"
            cli_path = acfg.get("cli_path", key)
            is_default = "是" if agents_cfg.get("default_backend") == key else ""
            # Check if CLI exists and get version
            _, rc = run_cmd(["which", cli_path])
            cli_status = "已安装" if rc == 0 else "未找到"
            ver_out, ver_rc = run_cmd([cli_path, "--version"], timeout=5)
            version = ver_out.split("\n")[0][:30] if ver_rc == 0 else ""
            self.agent_tree.insert("", "end", values=(name, enabled, cli_path, cli_status, version, is_default))

        # Platform tree
        self.platform_tree.delete(*self.platform_tree.get_children())
        platforms = [
            ("Slack", "slack"),
            ("Discord", "discord"),
            ("Telegram", "telegram"),
            ("飞书/Lark", "lark"),
            ("微信", "wechat"),
        ]
        enabled_platforms = cfg.get("platforms", {}).get("enabled", [])
        settings = get_settings()
        for name, key in platforms:
            pcfg = cfg.get(key, {})
            has_creds = bool(pcfg.get("bot_token") or pcfg.get("app_token") or pcfg.get("app_id"))
            is_enabled = key in enabled_platforms
            status_text = "已启用" if is_enabled else ("已配置" if has_creds else "未配置")
            # Count channels from settings
            channel_count = 0
            if isinstance(settings, dict):
                channels = settings.get(key, {}).get("channels", {})
                channel_count = len(channels) if isinstance(channels, dict) else 0
            self.platform_tree.insert("", "end", values=(name, "是" if has_creds else "否", status_text, channel_count))

        # Refresh sessions
        self._refresh_sessions()

        # Refresh logs if on that tab
        try:
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 4:  # logs tab
                self._refresh_logs()
        except Exception:
            pass

    def _update_card(self, card, text, color):
        card._var.set(text)
        card._label.configure(foreground=color)

    def _get_version(self):
        out, rc = run_cmd([str(VIBE_BIN), "version"])
        if rc == 0:
            return out
        return "未知"

    def _refresh_logs(self):
        source = self.log_source.get()
        if source == "main":
            lines = get_log_lines(500)
        elif source == "svc_out":
            lines = get_runtime_log(SERVICE_STDOUT, 300)
        elif source == "svc_err":
            lines = get_runtime_log(SERVICE_STDERR, 300)
        elif source == "ui_out":
            lines = get_runtime_log(UI_STDOUT, 300)
        elif source == "ui_err":
            lines = get_runtime_log(UI_STDERR, 300)
        else:
            lines = get_log_lines(500)

        # Apply keyword filter
        filt = self.log_filter.get().strip().lower()
        if filt:
            lines = [l for l in lines if filt in l.lower()]

        # Apply level filter
        level_filt = self.log_level_var.get()
        if level_filt != "ALL":
            level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
            min_level = level_order.get(level_filt, 0)
            filtered = []
            for l in lines:
                line_level = None
                for lv in level_order:
                    if f" {lv} " in l or f"-{lv}-" in l:
                        line_level = lv
                        break
                if line_level is None or level_order.get(line_level, 0) >= min_level:
                    filtered.append(l)
            lines = filtered

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")

        for line in lines:
            # Determine tag for coloring
            tag = "other"
            for level in LOG_COLORS:
                if f" {level} " in line or f"-{level}-" in line:
                    tag = level
                    break
            self.log_text.insert("end", line + "\n", tag)

        self.log_text.config(state="disabled")

        if self.log_auto_var.get():
            self.log_text.see("end")

    def _refresh_diagnostic(self):
        self.diag_text.config(state="normal")
        self.diag_text.delete("1.0", "end")

        # Run doctor and show results
        out, rc = run_cmd([str(VIBE_BIN), "doctor"], timeout=30)
        doctor_data = get_doctor()

        content = "=== 诊断报告 ===\n\n"
        if out:
            content += out + "\n\n"
        if doctor_data:
            content += "=== Doctor JSON ===\n"
            content += json.dumps(doctor_data, indent=2, ensure_ascii=False) + "\n"

        # System info
        content += "\n=== 系统信息 ===\n"
        content += f"Python: {sys.version.split()[0]}\n"
        content += f"Vibe Home: {VIBE_HOME}\n"
        content += f"Config: {'存在' if CONFIG_PATH.exists() else '不存在'}\n"
        content += f"Log: {'存在' if LOG_PATH.exists() else '不存在'} ({LOG_PATH.stat().st_size / 1024:.1f}KB)" if LOG_PATH.exists() else "Log: 不存在\n"

        self.diag_text.insert("1.0", content)
        self.diag_text.config(state="disabled")

    # ── Config tab helpers ────────────────────────────────────────────────

    def _load_config_tree(self):
        self.config_tree.delete(*self.config_tree.get_children())
        cfg = get_config()
        if not cfg:
            return
        self._add_config_node("", "config", cfg)

    def _add_config_node(self, parent, key, value):
        if isinstance(value, dict):
            node = self.config_tree.insert(parent, "end", text=key, values=("dict",))
            for k, v in value.items():
                self._add_config_node(node, k, v)
        elif isinstance(value, list):
            node = self.config_tree.insert(parent, "end", text=f"{key} [{len(value)}]", values=("list",))
            for i, v in enumerate(value):
                self._add_config_node(node, str(i), v)
        else:
            self.config_tree.insert(parent, "end", text=f"{key}: {value}", values=("value",))

    def _on_config_select(self, event):
        sel = self.config_tree.selection()
        if not sel:
            return
        cfg = get_config()
        path_parts = []
        node = sel[0]
        while node:
            item_data = self.config_tree.item(node)
            path_parts.insert(0, item_data["text"].split(":")[0].split(" [")[0])
            node = self.config_tree.parent(node)

        current = cfg
        for part in path_parts[1:]:
            if isinstance(current, dict):
                current = current.get(part, {})
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    current = {}
            else:
                current = {}

        self.config_text.delete("1.0", "end")
        if isinstance(current, (dict, list)):
            self.config_text.insert("1.0", json.dumps(current, indent=2, ensure_ascii=False))
        else:
            self.config_text.insert("1.0", str(current))

    def _save_config_from_text(self):
        try:
            data = json.loads(self.config_text.get("1.0", "end"))
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 错误", f"JSON 格式错误:\n{e}")
            return

        sel = self.config_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要保存的配置项")
            return

        cfg = get_config()
        path_parts = []
        node = sel[0]
        while node:
            item_data = self.config_tree.item(node)
            path_parts.insert(0, item_data["text"].split(":")[0].split(" [")[0])
            node = self.config_tree.parent(node)

        if len(path_parts) <= 1:
            save_config(data)
        else:
            current = cfg
            for part in path_parts[1:-1]:
                if isinstance(current, dict):
                    current = current.setdefault(part, {})
            last_key = path_parts[-1]
            if isinstance(current, dict):
                current[last_key] = data
            save_config(cfg)

        self._load_config_tree()
        messagebox.showinfo("成功", "配置已保存")

    def _open_config_editor(self):
        subprocess.Popen(["xdg-open", str(CONFIG_PATH)], start_new_session=True)

    def _reset_config(self):
        if not messagebox.askyesno("确认", "确定要重置配置为默认值吗？\n这将清除所有已配置的内容！"):
            return
        # Backup current config
        if CONFIG_PATH.exists():
            backup = CONFIG_PATH.with_suffix(".json.bak")
            CONFIG_PATH.rename(backup)
        # Remove config so vibe will recreate it
        CONFIG_PATH.unlink(missing_ok=True)
        self._load_config_tree()
        self.refresh()
        messagebox.showinfo("已重置", "配置已重置，请运行 `vibe` 重新配置")

    # ── Auto refresh ──────────────────────────────────────────────────────

    def _toggle_auto(self):
        self._auto_refresh = self.auto_var.get()

    def _schedule_auto_refresh(self):
        if self._auto_refresh:
            self.refresh()
        self.after(5000, self._schedule_auto_refresh)


# ── Dialogs ────────────────────────────────────────────────────────────────

class AgentConfigDialog(tk.Toplevel):
    def __init__(self, parent, agents_cfg):
        super().__init__(parent)
        self.title("Agent 配置")
        self.geometry("520x420")
        self.resizable(False, False)
        self.result = None
        self.transient(parent)
        self.grab_set()

        self.agents_cfg = dict(agents_cfg)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        for name, key in [("Claude Code", "claude"), ("Codex", "codex"), ("OpenCode", "opencode")]:
            frame = ttk.Frame(notebook, padding=10)
            notebook.add(frame, text=name)
            acfg = self.agents_cfg.get(key, {})

            ttk.Label(frame, text="启用:").grid(row=0, column=0, sticky="w", pady=4)
            enabled_var = tk.BooleanVar(value=acfg.get("enabled", False))
            ttk.Checkbutton(frame, variable=enabled_var).grid(row=0, column=1, sticky="w", pady=4)

            ttk.Label(frame, text="CLI 路径:").grid(row=1, column=0, sticky="w", pady=4)
            cli_var = tk.StringVar(value=acfg.get("cli_path", key))
            cli_entry = ttk.Entry(frame, textvariable=cli_var, width=40)
            cli_entry.grid(row=1, column=1, sticky="ew", pady=4)
            # Browse button
            ttk.Button(frame, text="...", width=3,
                       command=lambda v=cli_var: self._browse_cli(v)).grid(row=1, column=2, padx=2)

            ttk.Label(frame, text="默认模型:").grid(row=2, column=0, sticky="w", pady=4)
            model_var = tk.StringVar(value=acfg.get("default_model") or "")
            ttk.Entry(frame, textvariable=model_var, width=40).grid(row=2, column=1, sticky="ew", pady=4)

            ttk.Label(frame, text="空闲超时(秒):").grid(row=3, column=0, sticky="w", pady=4)
            timeout_var = tk.StringVar(value=str(acfg.get("idle_timeout_seconds", 600)))
            ttk.Entry(frame, textvariable=timeout_var, width=40).grid(row=3, column=1, sticky="ew", pady=4)

            frame.columnconfigure(1, weight=1)

            setattr(self, f"_{key}_enabled", enabled_var)
            setattr(self, f"_{key}_cli", cli_var)
            setattr(self, f"_{key}_model", model_var)
            setattr(self, f"_{key}_timeout", timeout_var)

        # Default backend
        default_frame = ttk.Frame(self, padding=(10, 0))
        default_frame.pack(fill="x")
        ttk.Label(default_frame, text="默认 Agent:").pack(side="left")
        self.default_var = tk.StringVar(value=self.agents_cfg.get("default_backend", "claude"))
        ttk.Combobox(default_frame, textvariable=self.default_var,
                     values=["claude", "codex", "opencode"], state="readonly", width=15).pack(side="left", padx=5)

        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="确定", command=self._on_ok).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side="right", padx=5)

    def _browse_cli(self, var):
        path = filedialog.askopenfilename(title="选择 CLI 路径")
        if path:
            var.set(path)

    def _on_ok(self):
        result = {"default_backend": self.default_var.get()}
        for key in ["claude", "codex", "opencode"]:
            enabled_var = getattr(self, f"_{key}_enabled")
            cli_var = getattr(self, f"_{key}_cli")
            model_var = getattr(self, f"_{key}_model")
            timeout_var = getattr(self, f"_{key}_timeout")
            try:
                timeout = int(timeout_var.get())
            except ValueError:
                timeout = 600
            result[key] = {
                "enabled": enabled_var.get(),
                "cli_path": cli_var.get().strip(),
                "default_model": model_var.get().strip() or None,
                "idle_timeout_seconds": timeout,
            }
        self.result = result
        self.destroy()


class PlatformConfigDialog(tk.Toplevel):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.title("IM 平台配置")
        self.geometry("560x520")
        self.resizable(False, False)
        self.result = None
        self.transient(parent)
        self.grab_set()

        self.cfg = dict(cfg)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Slack
        slack_frame = ttk.Frame(notebook, padding=10)
        notebook.add(slack_frame, text="Slack")
        slack_cfg = self.cfg.get("slack", {})
        self.slack_bot_token = self._field(slack_frame, "Bot Token:", slack_cfg.get("bot_token", ""), 0)
        self.slack_app_token = self._field(slack_frame, "App Token:", slack_cfg.get("app_token", ""), 1)
        self.slack_require_mention = self._check(slack_frame, "需要 @提及", slack_cfg.get("require_mention", False), 2)

        # Discord
        discord_frame = ttk.Frame(notebook, padding=10)
        notebook.add(discord_frame, text="Discord")
        discord_cfg = self.cfg.get("discord", {})
        self.discord_bot_token = self._field(discord_frame, "Bot Token:", discord_cfg.get("bot_token", ""), 0)
        self.discord_require_mention = self._check(discord_frame, "需要 @提及", discord_cfg.get("require_mention", False), 1)

        # Telegram
        telegram_frame = ttk.Frame(notebook, padding=10)
        notebook.add(telegram_frame, text="Telegram")
        telegram_cfg = self.cfg.get("telegram", {})
        self.telegram_bot_token = self._field(telegram_frame, "Bot Token:", telegram_cfg.get("bot_token", ""), 0)
        self.telegram_require_mention = self._check(telegram_frame, "需要 @提及", telegram_cfg.get("require_mention", True), 1)

        # Lark
        lark_frame = ttk.Frame(notebook, padding=10)
        notebook.add(lark_frame, text="飞书/Lark")
        lark_cfg = self.cfg.get("lark", {})
        self.lark_app_id = self._field(lark_frame, "App ID:", lark_cfg.get("app_id", ""), 0)
        self.lark_app_secret = self._field(lark_frame, "App Secret:", lark_cfg.get("app_secret", ""), 1)

        # WeChat
        wechat_frame = ttk.Frame(notebook, padding=10)
        notebook.add(wechat_frame, text="微信")
        wechat_cfg = self.cfg.get("wechat", {})
        self.wechat_bot_token = self._field(wechat_frame, "Bot Token:", wechat_cfg.get("bot_token", ""), 0)

        # Enabled platforms
        enabled_frame = ttk.Frame(self, padding=(10, 0))
        enabled_frame.pack(fill="x")
        ttk.Label(enabled_frame, text="已启用平台 (逗号分隔):").pack(side="left")
        enabled_list = self.cfg.get("platforms", {}).get("enabled", [])
        self.enabled_var = tk.StringVar(value=",".join(enabled_list))
        ttk.Entry(enabled_frame, textvariable=self.enabled_var, width=40).pack(side="left", padx=5)

        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="确定", command=self._on_ok).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side="right", padx=5)

    def _field(self, parent, label, default, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = tk.StringVar(value=default)
        show = "*" if "token" in label.lower() or "secret" in label.lower() else ""
        ttk.Entry(parent, textvariable=var, width=45, show=show).grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)
        return var

    def _check(self, parent, label, default, row):
        var = tk.BooleanVar(value=default)
        ttk.Checkbutton(parent, text=label, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        return var

    def _on_ok(self):
        self.cfg["slack"] = {
            "bot_token": self.slack_bot_token.get().strip(),
            "app_token": self.slack_app_token.get().strip(),
            "require_mention": self.slack_require_mention.get(),
        }
        self.cfg["discord"] = {
            "bot_token": self.discord_bot_token.get().strip(),
            "require_mention": self.discord_require_mention.get(),
        }
        self.cfg["telegram"] = {
            "bot_token": self.telegram_bot_token.get().strip(),
            "require_mention": self.telegram_require_mention.get(),
        }
        self.cfg["lark"] = {
            "app_id": self.lark_app_id.get().strip(),
            "app_secret": self.lark_app_secret.get().strip(),
        }
        self.cfg["wechat"] = {
            "bot_token": self.wechat_bot_token.get().strip(),
        }
        enabled = [x.strip() for x in self.enabled_var.get().split(",") if x.strip()]
        self.cfg["platforms"] = {"enabled": enabled, "primary": enabled[0] if enabled else ""}
        self.result = self.cfg
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = VibeRemoteManager()
    app.mainloop()
