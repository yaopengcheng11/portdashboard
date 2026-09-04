# Port Dashboard — 本地端口控制中心

本地 FastAPI Web 服务 + 端口监控面板，跨平台（**Windows / Linux / macOS**）单二进制部署。深绿与奶油白高对比度赛博朋克风格界面，免刷新实时监控托管项目与系统端口。

---

## 核心功能

### 🖥️ 项目生命周期管理
- **多标签页界面**：托管项目 / 本地端口 / 全局端口
- **场景（Scenes）** — 把若干项目按依赖顺序编组（后端在前），一键顺序启动（健康检查逐个放行、失败即中止）、逆序批量停止；已在跑或外部托管的步骤自动跳过。**配套组合自动检测**：依据前端配置/.env 里指向彼此端口的 localhost 引用（vite proxy、API_URL…）与去角色后缀后的同名项目，自动建议场景——扫描导入可一键"导入并建场景"，场景弹窗对已托管项目自动检测
- **扫描导入** — 指定根目录一键扫描（识别 package.json dev/start script、带 Web 依赖的 Python 入口），端口从 `.env` / vite·next·nuxt 配置 / 脚本参数推断，勾选批量导入
- 创建、编辑、删除托管项目（Vite、React、Python FastAPI、Node 等）
- 一键启动/关闭，跨平台进程树终止（Windows `taskkill` / Unix `kill -9`）
- **崩溃看护（可选）** — 项目开启 `auto_restart` 后，意外退出（崩溃/误杀）会被自动拉起，失败按 5–60 秒指数退避；手动「停止」不会被重启
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
- **自动刷新开关**：间隔可在设置面板内调整（3–60s），可随时暂停
- **自包含 CSS 设计系统**：零框架依赖，7 套主题由 8 个变量驱动，详见 DESIGN.md
- **本地托管字体**：JetBrains Mono latin 子集，无 CDN 依赖
- **分类过滤**：快速筛选不同类型的进程

### ⚙️ 用户偏好与设置面板

点击 header 右侧 **SETTING** 按钮打开设置弹窗，2 栏布局（左侧 200px 导航 + 右侧内容区，居中 720px × 80vh）：

| 分区 | 内容 |
|------|------|
| **主题 THEME** | 7 种配色（详见下方），点击立即切换并持久化 |
| **外观 APPEARANCE** | CRT 扫描线效果 toggle |
| **刷新 REFRESH** | 自动刷新 toggle + 刷新间隔（3 / 5 / 10 / 15 / 30 / 60 秒） |
| **默认视图 DEFAULTS** | 默认分类（all / user / creative）+ 默认标签页（managed / local / system） |
| **高级 ADVANCED** | 控制台绑定端口（修改需重启）+ 恢复默认设置 |

- **服务端持久化** —— `GET/PUT /api/preferences` 读写 `mydashboard-config.json`，跨会话保留
- **可配置项**：
  - `theme`: `dark-emerald` / `blueprint` / `midnight` / `arctic` / `terra` / `neon` / `velvet`
  - `default_category`: `all` / `user` / `creative`
  - `default_tab`: `managed` / `local` / `system`（首屏默认标签页）
  - `auto_refresh` (bool) + `refresh_interval` (3 / 5 / 10 / 15 / 30 / 60 秒)
  - `port`: 服务绑定端口（下次启动生效，默认 `9229`）
- **服务端默认值兜底** —— 启动时读取偏好文件，UI 在首次渲染前就用服务端默认值 hydrate，杜绝 FOUC
- **HTML 缓存控制** —— 仪表板 HTML 设 `Cache-Control: no-store`，改了 `app.py` 强制刷新就能看到

> 视觉规范见 [`DESIGN.md`](./DESIGN.md)（Cyberpunk CRT 主题 / 字体 / 组件 token）

---

## 跨平台支持

| 平台 | 支持状态 | 端口扫描 | 进程终止 |
|------|---------|---------|---------|
| **macOS**   | ✅ 一等公民 | 逐进程 `psutil.net_connections`（无 root 也可用） | `killpg` SIGTERM → 超时 SIGKILL |
| **Linux**   | ✅ 一等公民 | `psutil.net_connections`（procfs） | `killpg` SIGTERM → 超时 SIGKILL |
| **Windows** | ✅ 一等公民 | `netstat -ano` + `tasklist` / psutil | `taskkill /F /T` |

Unix 优先的细节（v2026.09-1 起与 Windows 完全对等，部分更强）：

- **python3 链路**：现代 macOS（12.3+）没有裸 `python`——自动发现生成的 Python 启动命令在
  Unix 上用 `python3`；用户从 Windows 拷来的配置写着 `python` 时，启动器会静默回退解析
- **HTTP 探测双栈**：v4 拒连时自动探测 `::1`——macOS 上 vite/next 绑 `localhost` 常只落 IPv6，
  这些服务的 HTTP 识别（含"访问页面"的 is_http 判断）不再漏报
- **核心守护保护**：WindowServer / securityd / mdnsresponder / sshd / systemd-resolved /
  dbus-daemon 等与 Windows 的 svchost/lsass 同级硬保护，前端"极危"评级同步
- **优雅停止是 Unix 默认**：`SIGTERM` → 等待 3s → `SIGKILL` 升级（Windows 为强制 taskkill）
- **开箱体验一致**：`start.sh` / `start.bat` 都会自动创建 `.venv` 并安装依赖，绑定地址与端口
  解析逻辑完全相同（默认 127.0.0.1）

> macOS 备注：系统级 `net_connections` 需要 root，逐进程枚举是常态路径
> （v2026.08-2 起），实测非 root 用户约四成系统进程会拒绝枚举，属正常跳过。

---

## 项目结构

```
portdashboard/
├── app.py                      # FastAPI 后端主程序（~1870 行）
│   ├── API 路由（23 个 endpoint：项目 / 端口 / 日志 / 偏好 / 发现 / 场景）
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
├── discovery.py                # 项目自动发现：扫目录识别可托管仓库 + 端口推断
├── scenes.json                 # 场景配置（用户数据，gitignore）
├── http_probe.py               # HTTP 服务探测模块（125 行）—— 真 web 内容判定
│   ├── check_http_port()       # 入口
│   ├── _send_request_and_read  # TCP socket I/O
│   ├── _response_is_web_content # 解析 status / headers / body
│   └── _status_ok / _has_web_content_type / _body_looks_like_html
│
├── start.bat / start.sh        # 跨平台启动脚本
├── projects.json               # 托管项目配置（数据文件）
├── running_pids.json           # 运行中 PID 缓存
├── templates/index.html        # 前端界面（Vue 3 + 自包含 CSS 设计系统）
├── static/fonts/*.woff2        # JetBrains Mono 子集（本地托管）
├── requirements-dev.txt        # UI 验证脚手架依赖（pytest + playwright + pillow）
├── tests/test_app.py           # 后端单元测试（端口扫描 / IPv6 / 进程去重 / 启动解析 / 看护退避）
├── tests/test_discovery.py     # 自动发现单测（端口推断优先级 / 深度限制 / 噪声目录）
├── tests/verify_ui.py          # Playwright 分阶段 UI 断言（7 主题 × 3 标签页截图、tone 分色、键盘契约等）
├── logs/*.log                  # 各项目的运行日志
├── mcp-server/                 # MCP Server：把面板 API 包装成 agent 可用的 tools
└── agent-harness/              # CLI 工具和测试（独立子项目）
```

> 跑 UI 验证：`pip install -r requirements-dev.txt && playwright install chromium && python3 tests/verify_ui.py --phase 0`
> 跑后端单测：`python3 -m pytest tests/test_app.py -v`

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

> 首次启动 `projects.json` 不存在（仓库不携带个人配置），可通过 UI 的「新建项目」按钮添加；或复制 [`projects.json.example`](./projects.json.example) 改写路径后启动。

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

### 场景（Scenes）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/scenes` | GET | 场景列表（含每步状态与 up_count） |
| `/api/scenes/suggest` | GET | 自动检测配套组合（端口引用 + 命名配套，拓扑排序） |
| `/api/scenes` | POST | 创建场景 `{name, steps}`，steps 去重保序即启动顺序 |
| `/api/scenes/{id}` | PUT / DELETE | 更新 / 删除场景 |
| `/api/scenes/{id}/start` | POST | 按顺序启动：managed/external 步骤跳过，失败即中止并返回逐步结果 |
| `/api/scenes/{id}/stop` | POST | 按相反顺序停止 |

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
| `/api/preferences` | PUT | **浅层 merge** 当前偏好 + 提交 patch（原子写）。非法键被 `_coerce_preferences` 静默丢弃，不会 422。改 `port` 字段时返回 `requires_restart: true` |

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
    auto_restart: bool = False  # 意外退出时自动重启（看护）

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
│  Vue 3 + 自包含 CSS · 7 套主题 · 复古 CRT 终端风格          │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP + SSE
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI app (app.py — ~1870 行)                             │
│  • 23 个 endpoint · DynamicCORSMiddleware · lifespan hook   │
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
| 后端模块总 LOC | ~2300 行（app.py + port_parser + http_probe + discovery） |
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

`mcp-server/` 是配套的 **MCP Server**：把面板 API 包装成 14 个 MCP tools（含场景启停），
让 ZCode / Claude 等 coding agent 可以直接扫端口、启停托管项目、读日志。
安装与注册方式见 [`mcp-server/README.md`](./mcp-server/README.md)。

---

## 许可证

MIT License

---

## 更新日志

### v2026.09-2 — 配套组合自动检测

- 🔎 **检测引擎**（`discovery.detect_project_groups`）—— 识别"要一起启动才能用"的项目：
  ① **端口引用**：项目配置/.env 里指向另一项目端口的 localhost URL（vite proxy target、
  next rewrite、`API_URL=http://localhost:8789`、`BACKEND_PORT=…` 等），连通分量即一组；
  ② **命名配套**：去掉 `-api/-web/-server/-client/-dashboard` 等角色后缀后同名的落单项目。
  组内拓扑排序（被依赖的在前，Kahn + 端口次序，有环兜底）
- 🧩 **两个入口**：扫描导入结果直接给出「导入并建场景」一键流（已托管成员自动并入场景、
  id 冲突自动改名）；场景弹窗打开时对已托管项目**自动检测**，建议卡一键创建（已存在同
  步骤的场景自动跳过）
- 🐛 **端口歧义防护**：多个项目声明同一端口（都吃 vite 默认 5173）时该端口不参与依赖
  归因，避免假依赖边；命名分组一律基于 slug（id/id_hint），中文显示名不再漏配
- ✅ 真机验证：`G:/AITOOLS` 正确检出 `cg-resource-hub-api → cg-resource-hub-web`
  （端口引用）与 `estudio-api → estudio`（同名）；已托管项目检出 hermes 对子；
  pytest 80 passed（+6 检测用例）；verify_ui 新增 P11 并全过

### v2026.09-1 — macOS/Linux 一等公民

**Unix 先行:**
- 🐍 **python3 命令链路** —— discovery 生成的 Python 启动命令在 macOS/Linux 用 `python3`
  （现代 macOS 12.3+ 已无裸 python）；`_resolve_executable` 对 Unix 上解析不到的 `python`
  静默回退 `python3` —— Windows 拷来的配置照样能跑
- 🌐 **HTTP 探测双栈** —— v4 拒连时再探 `::1`。macOS 上 vite/next 默认绑 `localhost` 时
  常只落 IPv6，此前这些服务在"本地端口"页永远识别不出 HTTP。真实 socket 回归测试覆盖
  v4 / ::1-only / raw TCP / 空端口四种情形
- 🛡️ **Unix 保护名单扩充** —— 新增 macOS（WindowServer / securityd / mdnsresponder /
  opendirectoryd / cfprefsd / diskarbitrationd / powerd / hidd）与 Linux（sshd /
  systemd-resolved / udevd / dbus-daemon / polkitd / networkmanager / snapd / rsyslogd /
  cron / atd）核心守护，与 Windows 的 svchost/lsass 同级硬保护；前端"极危"评级名单同步
- 📦 **start.bat 自动建 venv** —— 与 start.sh 对齐：没有 `.venv` 就自动创建并安装依赖，
  双平台开箱体验一致（真机验证：创建 → 装依赖 → 启动 → API 200）
- ⚖️ 停止语义本就 Unix 更优：`SIGTERM` → 等待 3s → `SIGKILL` 升级（Windows 为强制 taskkill）

**验证:**
- ✅ pytest 73 passed（`tests/test_cross_platform.py` 新增 19 个跨平台用例：
  双栈探测真 socket 断言、python3 回退 monkeypatch 断言、守护拒杀断言）

### v2026.09 — 安全修复 + 进程树感知 + MCP Server

**安全:**
- 🔒 **start.sh 不再绕过 loopback 安全默认** —— 之前 `./start.sh` 硬编码 `--host 0.0.0.0`，
  把 v2026.07-4 的「默认只绑 127.0.0.1」完全绕过（未鉴权的 kill/start API 暴露给整个局域网）。
  现在统一 `exec python3 app.py`，绑定地址与端口解析同 start.bat 完全一致；
  `dev` 参数与 `--reload` 都识别热重载（README 此前写的 `./start.sh dev` 现在真的生效了）
- 🔒 **项目 ID 校验收紧** —— id 会被用作日志文件名，现要求 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`，
  显式拒绝 Windows 保留设备名（con/nul/aux…，即使带 .log 也指向设备）与 `:`（NTFS 备用数据流）；
  `create_project` 此前是唯一不校验 id 的写入口，现已补上

**关键 bug fix:**
- 🐛 **Windows 上 npm/npx/vite 项目全部无法启动** —— list 形式 Popen 不按 PATHEXT 解析
  .cmd shim，README 自己的示例命令 `npm run dev` 直接 FileNotFoundError。
  启动前现在用 `shutil.which` 解析出真实可执行路径
- 🐛 **`dashboard_project` 标记在 Windows 上经常为 None** —— 启动链有中间层时
  （WindowsApps 存根、npm.cmd→cmd.exe→node），真正监听端口的 PID 是托管进程的
  **子孙**而非 Popen 直接子进程。标记与启动端口预检都改为进程树感知匹配
- 🐛 **PID 复用误认领** —— 认领只检查 pid_exists，PID 被无关进程复用后项目会显示
  running (Adopted)，停止时就会误杀。注册表现在写入 float `started_at`，
  认领与运行态判定都比对 psutil `create_time()`（旧格式无时间戳的条目放行，向后兼容）
- 🐛 **Unix 停止虚报成功** —— killpg 后无条件 `return True`。现在 SIGTERM →
  等待 3s → 超时升级 SIGKILL，按真实结果返回；`_kill_process_tree` 对已退出的
  目标返回 True（视为成功）而非 False
- 🐛 **`PUT /api/projects/{id}` 身份可被 body 篡改** —— body 的 id 与路径不一致时会整体
  写回，ACTIVE_PROCESSES / running_pids / 日志文件全部挂在旧 id 上变孤儿。现在以路径 id 为准

**其他修复:**
- 🐛 中文 Windows 上 tasklist/netstat 输出按 GBK 解码（此前 utf-8 + ignore 会吃掉非 ASCII 进程名）
- 🐛 端口缓存返回浅拷贝，下游 `group_ports_by_process` 的 is_http 回写与并发 JSON
  序列化存在竞态 —— 改为逐条 dict 拷贝
- 🐛 projects.json 损坏时静默返回空表，下次保存会覆盖原始数据 —— 现在改名隔离为
  `projects.json.corrupt-<ts>`
- 🐛 SSE 日志流在 chunk 边界把一行拆成两条事件 —— 加跨 chunk 行缓冲；
  日志被 clear 截断后从头部继续跟随（此前会永久静默）
- 🎨 新建/导入项目表单不再预填无效的 WSL 旧路径；日志面板仅当滚动位置在底部附近才自动跟随
- 🧹 CLI `api_get` 补齐与其余动词一致的 4xx 处理（此前直接抛 traceback）；
  删除 `categorize_process` 从未使用的 `ports` 参数

**新功能:**
- ✨ **MCP Server**（`mcp-server/`）—— 把面板 API 包装成 14 个 MCP tools
  （scan_ports / start / stop / tail_logs / scenes / kill…），coding agent 可直接操作面板。
  stdio transport，独立 venv，注册方式见 [mcp-server/README.md](./mcp-server/README.md)
- ✨ **启动场景（Scenes）** —— `scenes.json` 持久化 `{id, name, steps}`（steps 去重保序即启动顺序）。
  `POST /api/scenes/{id}/start` 逐个启动：已在托管运行（managed）或端口被外部服务（external）
  的步骤视为就绪跳过；某步失败立即中止（依赖语义），响应带逐步 results；停止按相反顺序。
  手动启动/停止路由重构为 `_start_project_core` / `_stop_project_core` 与场景共用同一条
  （预检、健康检查、看护播种全部继承）。托管页新增「场景」弹窗：状态徽章（n/m 运行中）、
  顺序 chips 新建表单、删除走自建对话框契约
- ✨ **扫描导入（项目自动发现）** —— 新模块 `discovery.py` + `GET /api/discover?root=...`。
  扫描根目录（含自身，深度可调，跳过 node_modules/.git/构建产物），识别两类项目：
  package.json 带 dev/start script 的 Node 项目；带 fastapi/uvicorn/flask 依赖 +
  app/main/server.py 入口的 Python 项目。端口推断优先级：`.env` 的 PORT >
  vite/next/nuxt/webpack 配置里的显式 port > 脚本里的 `--port/-p` > 框架默认值
  （vite 5173 / next·nuxt 3000 / web 8000）。托管页新增「扫描导入」弹窗：
  候选列表内联改命令/端口、已在管项目自动禁选、勾选批量导入（id 冲突自动改名重试）
- ✨ **崩溃看护** —— 项目新增 `auto_restart` 开关（项目表单复选框）。开启后 watchdog
  后台线程每 5s 巡检：托管进程意外退出即自动拉起，失败按 5/10/20/40/60s 指数退避，
  连续存活 60s 清零；手动停止/删除会被抑制（直到下次手动启动）；重启前做端口预检，
  端口仍被外部占用时暂停并记日志。期望状态在手动启动成功时播种，
  避免两次巡检之间"启动即崩"的进程永远无法被观察到。所有动作写入项目日志（`[watchdog]` 前缀）

**验证:**
- ✅ `tests/test_app.py` + `tests/test_discovery.py` 合计 54 passed（id 校验 / PID 复用防护 /
  可执行解析 / 看护退避 / 发现推断优先级 / 场景步骤去重）
- ✅ MCP stdio 握手（14 tools）+ 真机端到端（建项目→启动→扫端口→读日志→停止→删除）全链路通过
- ✅ 看护真机 E2E：杀整棵进程树 → 5s 内自动拉起（新 PID 监听）→ 日志含 `[watchdog]` →
  手动停止后 16s 确认不再被拉起
- ✅ 场景真机 E2E：顺序启动两端口监听 → 重复启动跳过 → 逆序停止全下线 → scenes.json 持久化
- ✅ 真机扫描 `G:/AITOOLS`：发现 12 个候选，端口推断逐项可溯源（.env / vite.config / script flag）
- ✅ `tests/verify_ui.py --phase 10` 全部通过（P9 扫描导入 + P10 场景弹窗断言；
  tone 分色 / sticky 表头 / 对话框键盘契约 / 零控制台错误）

### v2026.07-4 — 安全收紧 + 快照去重

**安全:**
- 🔒 **默认绑定 loopback (`127.0.0.1`)** —— 之前无条件 `0.0.0.0`，意味着同 LAN 的任何主机都能访问未鉴权的管理 API。需要对外暴露时显式设环境变量 `MYDASHBOARD_HOST=0.0.0.0` 才生效
- 🔒 **CORS 白名单收紧** —— 之前把每个活动本地端口都加进 CORS allowlist（任何本地页面都可带 cookie 跨域调用），现在只放行面板自身的 origin（`http://localhost:<port>` + `http://127.0.0.1:<port>`）

**性能 / 隐性 bug:**
- ⚡ HTTP 探测 + PID → 进程名推断做 TTL 缓存（之前每次刷新都重探测每个端口 + 重读元数据 + 每个 PID 组起线程池）
- ⚡ `running_pids.json` 一次刷新只写一次（之前每组都写）
- 🐛 **修复 `RUNNING_PORT` 永远是 `None`** —— uvicorn 重新 import 模块，`if __name__ == "__main__":` 块里的赋值永远不会到达请求路径。改为在 FastAPI app 启动时显式设置
- ⚡ 启动等待改为 async —— 慢的 health check 不会再 pin 死 worker

**验证:**
- ✅ `tests/test_app.py` 新增 92 行覆盖上述修复（loopback 绑定 / CORS allowlist / 缓存去重 / 启动异步）

### v2026.08 — 全站自包含设计系统 + 移除 Tailwind

**架构:**
- 🏗️ **彻底移除 Tailwind**。此前 `static/tailwind.min.css` 是过期的 purge 残骸（19KB / 274 类），
  而内联的 `tailwind.config` 用的是 Play CDN 写法却没有对应 runtime，**每次加载都抛 ReferenceError**，
  这意味着全部 44 个 `hermes-*` 颜色类从未生效过一天。现已删除框架、配置与样式文件
- 🎨 **`pd-*` 组件库 + tone 契约**：组件只声明语义 tone（ok/info/warn/danger/self/creative/network/muted），
  具体色值逐主题校准。4 个安全等级 + 5 个进程分类 + 3 个项目状态共 12 种配色只需一套组件 CSS
- 🔤 **JetBrains Mono 真正落地**：DESIGN.md 一直要求它，但项目里既无 `@font-face` 也无字体文件。
  现打包 latin 子集本地托管（2 × 21KB）
- 📐 DESIGN.md 全文重写为 v2，含「v1 → v2 废弃对照表」

**交互:**
- 💬 **自建对话框 + toast**，替换全部 29 处原生 `alert()` / `confirm()`。
  对话框基于 Promise，支持 Esc 取消 / Enter 确认 / 焦点自动落确认键
- ⌨️ 补齐 ESC 关闭与 `⌘,` 打开设置（界面上一直有提示但从未实现）

**顺带修掉的隐性 bug:**
- 🐛 CPU / 内存进度条**此前完全不可见**（填充条依赖缺失的 `bg-hermes-accent`）
- 🐛 header 弹性空隙**永久隐藏**（`md:block` 在裁剪版里不存在）
- 🐛 约 40 处边框渲染成 Tailwind preflight 的灰线 `#e5e7eb`
- 🐛 创意软件 / 网络工具分类徽章**从来没有颜色**（violet/blue 类全缺）
- 🐛 sticky 表头不生效（挂在 `tr` 上且表格是 `border-collapse`）
- 🐛 arctic 亮底主题下终端、滚动条、CRT 扫描线仍是深绿（颜色全硬编码）
- 🐛 `.retro-border:hover` 在任何主题下都闪回 Emerald 配色
- 🐛 `[v-cloak]` 规则缺失，首帧会闪 `{{ }}` 原文
- 🐛 超长进程名顶出操作按钮（`min-w-0` 缺失导致 truncate 失效）
- 🐛 删除死代码 `.glow-led`（无 background，光晕从来不可见）与 `.spin-refresh`（零调用）

**验证:**
- ✅ `tests/verify_ui.py` —— 分阶段 Playwright 断言：7 主题 × 3 标签页截图、
  零灰边框、tone 分色、对比度审计、sticky 表头、高度链、CRT 契约、
  对话框键盘契约，以及把原生弹窗打桩为 throw 以证明零残留

### v2026.08-2 — macOS 端口扫描重构 + 项目列表修复

**macOS 端口扫描（关键 bug fix）:**
- 🐛 **macOS 用户从未看到过任何端口**。旧实现用 `netstat -lnp`，
  但 macOS 的 `-p` 是 protocol 参数、地址分隔符是 `.` 而非 `:`、
  且根本不输出 PID 列 —— 三者叠加，进程以 64 退出，**结果永远为空**。
  改走逐进程 `psutil.net_connections(kind="tcp")` 枚举，跟平台实际能力对齐
- 🐛 **killProcess 永远拿到 `Unknown` 进程名**。调用方硬传 `platform='windows'`，
  在 macOS / Linux 上 `systemPorts.find(pid && port && platform=='windows')`
  永远不命中 → processName 退化为 `Unknown` → 基于进程名的安全规则
  （svchost / mysqld / clash 等）全部失效。改为只按 pid+port 匹配
- 🔧 `parse_listening_ports` 拆出 `format_addr(ip, port)` helper，
  IPv6 强制加方括号（`[::1]:4403` 而非 `::1:4403`，避免跟端口号混淆）
- 🔧 `_parse_unix_listening` 整段删除（macOS 路径），替换为
  `_listening_from_psutil_procs`，带 `proc_iter` 注入参数便于单测
- 🔧 `parse_listening_ports(pid_to_name)` 签名瘦身：
  Windows 仍要 `pid_to_name`（来自 `tasklist` 文本解析），
  Unix 路径从进程对象里直接拿 name，调用方无需白建 600+ 条的映射

**端口/项目上下文增强:**
- ✨ **每条端口 + 每个进程组都带 `cwd` 字段**。
  `node` / `python3.11` 这种同质化进程名之前完全分不清是哪个项目，
  现在 UI 在卡片标题下单独显示一行工作目录（深色 mono 风格）
- ✨ **进程组标题优先用 `project_name`**，回退到 `process_name`；
  进程名作为 hint 副标题。`cwd` 单独成行，三层信息分开
- ✨ **外部进程"强制停止"按钮**：原本"外部运行中"那个信息按钮
  升级为真能 kill 的危险色按钮（受高危安全锁保护，需二次确认），
  旁边一个 icon 按钮看说明
- ✨ `app.group_ports_by_process` 字段拆分：`project_name` 与 `cwd` 各管各的，
  不再借 `project_name` 当 cwd 的占位

**验证:**
- ✅ `tests/test_app.py::TestListeningPorts` —— 7 个新单测：
  字段形状 / IPv6 括号 / 同端口去重（先到先得）/ 跳过非 LISTEN /
  AccessDenied 进程跳过 / `parse_listening_ports({})` 真机烟雾测试
  （在 CI 上这条是能抓住 macOS 净空列表回归的关键断言）
- 🧹 `app._parse_ports_netstat` 重命名为 `_parse_ports_fallback`，
  注释明确"macOS 上 psutil 系统级调用需要 root，这条回退是常态路径"

### v2026.07-3 — 设置面板 UI 重设 + 主题卡紧凑化

**UI 重设:**
- ✨ **SETTING 按钮位置优化** —— 从 header 中间（夹在 LOGO 与状态卡之间）挪到与 LOGO 同行右侧，使用 `flex-1` 弹性空间分隔，齿轮 icon 琥珀色 + hover 旋转 45° 动画 + 悬停显示 ⌘, 快捷键提示
- ✨ **Settings 弹窗全新设计** —— 三段布局：Header（图标 + eyebrow "SETTINGS / 设置" + 主标题 "控制中心偏好" + 当前主题 chip + ✕ 关闭），Sidebar 168px（5 个分区:主题/外观/刷新/默认视图/高级，各带 icon + 中英双语标签 + 选中态左侧 3px 色条 + 琥珀背景），Content 区加大到 560px（主题卡 2 列网格 + toggle/segmented/input 等组件），Footer（自动保存状态指示 + 关闭/保存并关闭双按钮），780px × 82vh 居中阴影浮层 + fade/pop 入场动画
- ✨ **主题卡紧凑化** —— 从"3 列巨型彩色预览卡(~80px 高 × 250px 宽)"改为"2 列紧凑行(~50px 高 × 200px 宽)"，左侧 12px swatch 圆点带 glow，中间双行文字(Emerald / 深绿琥珀)，右上对勾表示选中态；7 张卡 4 行展示完，无滚动条
- 🔧 **CSS 块位置修正** —— Vue 模板内 `<style>` 块被当作副作用标签忽略导致 CSS 不生效；移到 `<head>` 内 `<title>` 之后，所有 `.settings-*` 样式正常加载
- 🔧 **header 布局重构** —— 从 `justify-between` 三栏(LOGO + SETTING + 4 状态卡)改为 LOGO + flex-1 弹性空间 + SETTING + 4 状态卡，SETTING 不再跟状态卡抢右侧空间


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
- ✨ **设置面板 UI 落地** —— header 与 LOGO 同行的 `SETTING` 按钮（齿轮 icon + hover 旋转 + ⌘, 快捷键提示），弹窗采用三段布局：Header（图标 + 双行标题 + 当前主题标签 + 关闭）、Sidebar（168px，5 个分区带 icon + 中英双语 + 选中态左侧色条）、Content（560px，主题卡 2 列紧凑布局 + toggle/segmented/input 等组件）、Footer（自动保存提示 + 关闭/保存按钮），780px × 82vh 居中阴影浮层，7 个主题实时切换（dark-emerald / blueprint / midnight / arctic / terra / neon / velvet），所有偏好改动即时持久化到后端
- ✨ **服务端默认值 hydrate** —— UI 首屏渲染前就有 theme/refresh 配置,避免 FOUC
- ✨ **HTML `Cache-Control: no-store`** —— 仪表板强制不走缓存,改后端代码即可见

**设计规范：**
- 📐 新增 `DESIGN.md` —— Cyberpunk CRT 终端主题(深绿 #041c1c + 奶油白 #FFE6CB + 琥珀 #FFBD38)+ JetBrains Mono 字体 + 组件 token

**仓库整理：**
- 🔧 `.gitignore` 加 `mydashboard-config.json` / `.hermes/` / `*.bak-*` / `static/vue.global.prod.js` 等 7 条,避免本地污染
- 🔧 总 LOC：1116 → 1500（含新功能 + 两个独立模块）