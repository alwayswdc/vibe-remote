# Vibe Remote (Enhanced) 安装与使用指南

基于 [vibe-remote](https://github.com/cyhhao/vibe-remote) 的增强版本，新增截图、文件发送、Windows resume 修复、跨项目会话搜索、Bot 命令菜单、桌面管理工具等功能。

---

## 前置条件

- **Python 3.10+**（已验证 3.13）
- **Node.js 18+**（构建 Web UI 前端需要）
- 至少一个 AI Agent：Claude Code / OpenCode / Codex

---

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/wdc63/vibe-remote.git
cd vibe-remote
```

### 2. 安装 Python 依赖（editable 模式）

```bash
pip install -e .
```

这样改代码立即生效，无需重新安装。

### 3. 构建 Web UI 前端

```bash
cd ui
npm install
npm run build
cd ..
```

**这步不能跳过**，否则 Web UI 会返回 `{"error":"not_found"}`。

### 4. 启动

```bash
vibe
```

浏览器会自动打开 `http://127.0.0.1:5123`，按向导配置即可。

---

## 桌面管理工具

双击桌面上的 **Vibe Remote Manager** 快捷方式，可以：

| 功能 | 说明 |
|------|------|
| ▶ Start / ■ Stop / ↻ Restart | 管理服务生命周期 |
| 状态显示 | 运行/停止、PID、运行时长 |
| 实时日志 | 自动滚动显示最新日志 |
| Auto-start on login | 开机自动启动（注册表方式，无需管理员） |
| Web UI | 一键打开 Web 管理界面 |
| Config | 打开配置文件目录 |
| Data Folder | 打开数据目录 `~/.vibe_remote/` |

也可以直接运行：

```bash
python vibe_manager.pyw
```

---

## 开机自动启动

安装时已自动启用。如需手动管理：

```bash
# 查看是否启用
python -c "from vibe_manager import is_autostart_enabled; print(is_autostart_enabled())"

# 启用
python -c "from vibe_manager import enable_autostart; enable_autostart()"

# 禁用
python -c "from vibe_manager import disable_autostart; disable_autostart()"
```

---

## 新增功能说明

### 1. 远程截图

在 Telegram 中：
- `/screenshot` — 截取全屏
- `/window` — 选择窗口截图
- 主菜单新增 📸 Screenshot 和 🪟 Window 按钮

Agent 也可以自己截图（通过 Bash 调用 CLI）：
```bash
python vibe_screenshot_cli.py              # 全屏
python vibe_screenshot_cli.py window       # 前台窗口
python vibe_screenshot_cli.py title Chrome # 按标题
python vibe_screenshot_cli.py hwnd 12345   # 按 HWND
python vibe_screenshot_cli.py list         # 列出窗口
```

### 2. 文件与图片发送

Agent 回复中可以使用 `file://` 协议发送文件：
- `[文件](file:///path/to/file.pdf)` → 发送为文件附件
- `![截图](file:///path/to/screenshot.png)` → 发送为图片

### 3. Telegram Bot 命令菜单

输入 `/` 会弹出命令列表，输入框旁出现 M 菜单按钮。

### 4. /resume 增强

- 修复 Windows 路径编码 bug（原版在 Windows 上几乎无法使用）
- 支持跨项目会话搜索和恢复，自动使用正确的 working directory
- 显示项目名标签区分不同项目的会话

---

## 常见问题

### Web UI 报 `{"error":"not_found"}`

前端没有构建。执行：
```bash
cd ui && npm install && npm run build && cd ..
```

### Telegram 报 `Conflict: terminated by other getUpdates request`

有多个 vibe-remote 实例在跑。先全部停掉再启动：
```bash
vibe stop
# 等几秒
vibe
```

### Python 进程占满 CPU

同上，有僵尸进程。用管理工具 Stop 或 `vibe stop` 清理。

---

## 与原版的差异

| | 原版 | 增强版 |
|---|---|---|
| Windows /resume | 基本不可用 | 完全修复 |
| 跨项目会话 | 不支持 | 支持搜索、恢复、项目名标签 |
| 截图 | 无 | 全屏/窗口/按标题/按HWND/窗口选择器 |
| 文件发送 | 仅文本 | file:// 协议支持文件和图片 |
| Bot 命令菜单 | 无 | / 弹出命令列表 + M 菜单按钮 |
| 桌面管理工具 | 无 | tkinter GUI + 开机自启动 |
| session_working_paths 清理 | 无（会膨胀） | 同步清理 |
