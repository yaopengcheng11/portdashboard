# Port Dashboard — 本地端口控制中心

本地 FastAPI Web 服务 + 端口监控面板，跨平台（**Windows / Linux / macOS**）单二进制部署。深绿与奶油白高对比度赛博朋克风格界面，免刷新实时监控托管项目与系统端口。

---

## 核心功能

### 🖥️ 项目生命周期管理
- **多标签页界面**：托管项目 / 本地端口 / 全局端口
- 创建、编辑、删除托管项目（Vite、React、Python FastAPI、Node 等）
- 一键启动/关闭，跨平台进程树终止（Windows `taskkill` / Unix `kill -9`）
- **启动前端口冲突预检** — 自动识别外部进程占用，拒绝启动并提示
- **启动超时 + 健康检查** — 可配置 `startup_timeout_sec` 与 `health_check_url`，启动失败自动清理
- 断电重启后自动通过 PID 重新接管之前由面板启动的进程
- 外部运行识别：端口被外部进程占用时标记为"外部运行中"
- 可选自动同步项目名称（读取 `package.json` / `pyproject.toml`）

### 🌐 本地端口智能检测
- **按进程分组**：自动合并同一进程的多个端口
- **dashboard_project 反向标记**：每条端口带"是否由本面板管理"的字段
- **HTTP 服务自动识别**：检测真实网页内容（支持 HTML/JSON/XML 等）
- **进程分类与过滤**：
  - 🟢 用户应用（User）/ 🔵 系统服务（System）/ 🟣 创意软件（Creative）/ 🟠 网络工具（Network）
- **安全评估徽章**：每个进程显示安全等级和功能描述

### 📊 实时控制台日志（SSE 流式）
- 每个项目的控制台输出重定向至 `logs/{project_id}.log`
- **`/api/projects/{id}/logs/stream`** —— Server-Sent Events 实时推送新日志行（无需轮询）
- 历史日志通过 `/api/projects/{id}/logs` 拉取
- 支持一键清除 / 复制

### 🔒 活动端口扫描与安全防护
- 扫描所有 TCP LISTENING 端口及对应进程
- 智能安全评级：安全 / 警告 / 极危
- 高危安全锁 + 二次确认
- 系统进程硬核强锁保护（Windows/Linux/macOS 各平台关键进程）

### 📈 系统监控看板
- 实时 CPU / 内存负载条
- 主机 IP、运行时间
- 动态操作系统检测

### 🎨 界面特性
- **自动刷新开关**：3 秒间隔轮询，可随时暂停
- **跨平台 Tailwind CSS**：本地静态文件，无需 CDN
- **动态 CORS 配置**：自动放行当前监听端口的跨域请求
- **分类过滤**：快速筛选不同类型的进程

### ⚙️ 用户偏好与设置面板
- **服务端持久化** —— `GET/PUT /api/preferences` 读写 `mydashboard-config.json`,跨会话保留
- **可配置项**:
  - `theme`: `dark-emerald` / `blueprint`
  - `default_category`: `all` / `user` / `creative`
  - `auto_refresh` + `refresh_interval` (3 / 5 / 10 / 15 / 30 / 60 秒)
  - `port`: 服务绑定端口(下次启动生效,默认 `9229`)
- **服务端默认值兜底** —— 启动时读取偏好文件,UI 在首次渲染前就用服务端默认值 hydrate,杜绝 FOUC
- **HTML 缓存控制** —— 仪表板 HTML 设 `Cache-Control: no-store`,改了 `app.py` 强制刷新就能看到

> 视觉规范见 [`DESIGN.md`](./DESIGN.md)(Cyberpunk CRT 主题 / 字体 / 组件 token)

---

## 跨平台支持

| 平台 | 支持状态 | 端口扫描 | 进程终止 |
|------|---------|---------|---------|
| **Windows** | ✅ 完整 | `netstat -ano` + `tasklist` | `taskkill /F /T` |
| **Linux**   | ✅ 完整 | `netstat -tlnp` + psutil | `killpg` + SIGTERM/kill |
| **macOS**   | ✅ 完整 | `netstat -lnp` + psutil | `killpg` + SIGTERM/kill |

---

## 项目结构

```
portdashboard/
├── app.py                      # FastAPI 后端主程序（1188 行）
│   ├── API 路由（19 个 endpoint）
│   ├── 进程管理（start/stop/terminate）
│   ├── 项目 CRUD + 持久化
│   ├── 日志管理（SSE 流式 + 历史）
│   └── 端口预检 + 健康检查
│
├── port_parser.py              # 端口解析模块（188 行）—— 平台独立 helper
│   ├── build_pid_name_map()    # Windows: tasklist / Unix: psutil
│   ├── parse_listening_ports() # 跨平台 netstat 解析
│   └── _parse_windows_listening / _parse_unix_listening
│
├── http_probe.py               # HTTP 服务探测模块（125 行）—— 真 web 内容判定
│   ├── check_http_port()       # 入口
│   ├── _send_request_and_read  # TCP socket I/O
│   ├── _response_is_web_content # 解析 status / headers / body
│   └── _status_ok / _has_web_content_type / _body_looks_like_html
│
├── start.bat / start.sh        # 跨平台启动脚本
├── projects.json               # 托管项目配置（数据文件）
├── running_pids.json           # 运行中 PID 缓存
├── templates/index.html        # 前端界面（Vue 3 + Tailwind）
├── static/tailwind.min.css     # 本地 Tailwind（离线可用）
├── logs/*.log                  # 各项目的运行日志
└── agent-harness/              # CLI 工具和测试（独立子项目）
```

---

## 快速上手

### 环境要求
- **Python 3.11+**
- 依赖：`fastapi`, `uvicorn`, `psutil`

### 安装

**Windows：**
```bash
cd portdashboard
python -m venv .venv
.venv\Scripts\pip install fastapi uvicorn psutil
```

**Linux / macOS：**
```bash
cd portdashboard
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn psutil
```

### 启动

**Windows：** 双击 `start.bat` 或：
```bash
start.bat          # 稳定模式
start.bat dev      # 开发模式（热重载）
```

**Linux / macOS：**
```bash
./start.sh         # 稳定模式
./start.sh dev     # 开发模式（热重载）
```

访问 **http://localhost:9229/**

---

## API 端点

### 系统

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/system/stats` | GET | 系统统计（CPU / 内存 / IP / 运行时间） |
| `/api/system/ports` | GET | 所有活动端口（含 `dashboard_project` 字段） |
| `/api/system/ports/kill/{pid}` | POST | 终止指定 PID 的进程 |

### 仪表板

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/snapshot` | GET | 完整仪表板快照 |

### 项目管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects` | GET | 托管项目列表 |
| `/api/projects` | POST | 创建项目 |
| `/api/projects/{id}` | PUT | 更新配置 |
| `/api/projects/{id}` | DELETE | 删除项目 |

### 进程控制

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects/{id}/start` | POST | 启动项目（含端口预检 + 健康检查） |
| `/api/projects/{id}/stop` | POST | 停止项目 |

### 日志

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects/{id}/logs` | GET | 历史日志（分页） |
| `/api/projects/{id}/logs/stream` | GET | **SSE 流式**新日志（实时推送） |
| `/api/projects/{id}/logs/clear` | POST | 清除日志 |

### 偏好 (设置面板)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/preferences` | GET | 读取当前偏好 + 服务端默认值,返回 `{ "preferences": {...}, "defaults": {...} }` |
| `/api/preferences` | PUT | 整体替换(原子写) + schema 校验,非法值返回 422 |

存储位置：`mydashboard-config.json`(项目根目录,运行时不需手动编辑)。

---

## 高级配置：项目 Pydantic 模型

```python
class Project(BaseModel):
    id: str                     # 项目唯一 ID（URL-safe）
    name: str                   # 显示名
    cwd: str                    # 工作目录
    command: str                # 启动命令（支持 env=value 前缀）
    port: int                   # 期望监听的端口（启动时预检）
    description: Optional[str]  # 描述
    sync_name: bool = False     # 自动从 package.json 同步 name

    # v2026.07 — 启动控制
    startup_timeout_sec: int = 30   # 启动超时（1..300 秒）
    health_check_url: str = ""      # 启动后 GET 探测此 URL，2xx 即视为 ready
```

**示例：配置 30s 启动超时 + 健康检查**

```json
{
  "id": "nexart-workflow",
  "name": "NexArtWorkFlow",
  "cwd": "G:/AITOOLS/NexArtWorkFlow",
  "command": "npm run dev",
  "port": 5173,
  "startup_timeout_sec": 60,
  "health_check_url": "http://localhost:5173"
}
```

启动失败时的日志示例：
```
[startup check FAILED] timeout after 60s (no health URL configured)
```

---

## 启动预检机制

`POST /api/projects/{id}/start` 启动前自动执行 **端口冲突预检**：

```python
# 伪代码
active_ports = get_active_system_ports(force_refresh=True)
conflict = next((p for p in active_ports if p["port"] == project["port"]), None)
if conflict and not is_dashboard_managed(conflict["pid"]):
    raise HTTPException(409, "Port 5173 is already in use by external process 'node' (PID 12345).")
```

返回示例：
```json
{
  "detail": "Port 5173 is already in use by external process 'node' (PID 12345). Stop it first or change the project's port."
}
```

避免误启动造成端口冲突 / 资源浪费。

---

## 开机自启（可选）

**Windows - Task Scheduler：**
1. 打开"任务计划程序" → 创建基本任务
2. 触发器：用户登录时
3. 操作：启动程序
   - 程序：`G:\AITools\portdashboard\.venv\Scripts\pythonw.exe`
   - 参数：`app.py`
   - 起始于：`G:\AITools\portdashboard`

**Linux - systemd user service：**
```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/portdashboard.service << 'EOF'
[Unit]
Description=Port Dashboard
After=network.target

[Service]
Type=simple
ExecStart=%h/portdashboard/.venv/bin/python %h/portdashboard/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable portdashboard
systemctl --user start portdashboard
```

**macOS - LaunchAgent：**
```bash
cat > ~/Library/LaunchAgents/com.portdashboard.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.portdashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/USERNAME/portdashboard/.venv/bin/python</string>
        <string>/Users/USERNAME/portdashboard/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.portdashboard.plist
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (http://localhost:9229/)                            │
│  Vue 3 + Tailwind CSS · 自动刷新（3s）· 赛博朋克风格       │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP + SSE
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI app (app.py — 1188 行)                              │
│  • 19 个 endpoint · DynamicCORSMiddleware · lifespan hook   │
│  • 端口预检 · 健康检查 · SSE 日志流                          │
└──────┬────────────────────────┬─────────────────────────────┘
       │                        │
       ▼                        ▼
┌──────────────┐         ┌─────────────────┐
│ port_parser  │         │  http_probe     │
│  (188 行)    │         │  (125 行)       │
│              │         │                 │
│ • tasklist   │         │ • TCP socket    │
│ • netstat    │         │ • HTTP parse    │
│ • psutil     │         │ • HTML detect   │
└──────┬───────┘         └────────┬────────┘
       │                          │
       ▼                          ▼
┌──────────────────────────────────────────┐
│  OS (Windows / Linux / macOS)             │
│  subprocess · psutil · signal            │
└──────────────────────────────────────────┘
```

---

## 性能 / 代码质量（最近一次重构）

| 指标 | 数值 |
|------|------|
| 后端模块总 LOC | ~1500 行 |
| `app.py` 最大函数 cognitive | 39（`start_project`） |
| 跨文件 helper 数 | 9 |
| 跨文件 CALLS 边（cbm 索引） | 1300 |

核心模块拆分：
- **`port_parser.py`** —— 把 `_parse_ports_netstat`（c=26, cog=97, L=106）拆为 5 个平台独立 helper，主函数降到 c=1
- **`http_probe.py`** —— 把 `check_http_port`（c=17, cog=46, L=59）拆为 5 个职责清晰的小函数，主入口 c=0

---

## 配套工具

`agent-harness/` 是配套的 **CLI 客户端 + 测试 + skill 集合**：

```
agent-harness/
├── cli_anything/portdashboard/   # CLI 客户端（620 行 Python）
├── skills/                        # Claude skill 集成
├── tests/                         # pytest 套件
└── setup.py
```

CLI 客户端可独立运行，提供与 Web dashboard 等价的命令式操作。

---

## 许可证

MIT License

---

## 更新日志

### v2026.07 — 模块化重构 + 4 项功能升级

**新功能：**
- ✨ **启动超时 + 健康检查** —— `Project.startup_timeout_sec` + `health_check_url` 字段，启动失败自动清理
- ✨ **端口冲突预检** —— 启动前强制刷新端口快照，409 错误返回外部占用方详情
- ✨ **SSE 日志流式推送** —— `GET /api/projects/{id}/logs/stream` 实时推送新日志
- ✨ **`dashboard_project` 字段** —— `/api/system/ports` 每条端口标记"是否由本面板管理"

**代码结构：**
- 🔧 拆分 `_parse_ports_netstat`(c=26→1, cog=97→1)→ 新文件 `port_parser.py`
- 🔧 拆分 `check_http_port`(c=17→1, cog=46→1)→ 新文件 `http_probe.py`

### v2026.07-2 — 用户偏好 + 设计规范

**新功能：**
- ✨ **设置面板 (`/api/preferences`)** —— 主题 / 默认分类 / 自动刷新 / 刷新间隔 / 绑定端口,服务端 `mydashboard-config.json` 持久化
- ✨ **服务端默认值 hydrate** —— UI 首屏渲染前就有 theme/refresh 配置,避免 FOUC
- ✨ **HTML `Cache-Control: no-store`** —— 仪表板强制不走缓存,改后端代码即可见

**设计规范：**
- 📐 新增 `DESIGN.md` —— Cyberpunk CRT 终端主题(深绿 #041c1c + 奶油白 #FFE6CB + 琥珀 #FFBD38)+ JetBrains Mono 字体 + 组件 token

**仓库整理：**
- 🔧 `.gitignore` 加 `mydashboard-config.json` / `.hermes/` / `*.bak-*` / `static/vue.global.prod.js` 等 7 条,避免本地污染
- 🔧 总 LOC：1116 → 1500（含新功能 + 两个独立模块）