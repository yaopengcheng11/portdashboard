# Port Dashboard - 本地端口控制中心

本地网页服务及端口监控面板，支持 **Windows / Linux / macOS** 跨平台运行。提供深绿与奶油白高对比度赛博朋克风格界面，免刷新实时监控。

---

## 核心功能

### 🖥️ 项目生命周期管理
- **多标签页界面**：托管项目 / 本地端口 / 全局端口
- 创建、编辑、删除托管项目（Vite、React、Python FastAPI、Node 等）
- 一键启动/关闭，跨平台进程树终止（Windows `taskkill` / Unix `kill -9`）
- 断电重启后自动通过 PID 重新接管之前由面板启动的进程
- 外部运行识别：端口被外部进程占用时标记为"外部运行中"
- 可选自动同步项目名称（读取 `package.json` / `pyproject.toml`）
- 项目名称智能识别（基于工作目录推断）

### 🌐 本地端口智能检测
- **按进程分组**：自动合并同一进程的多个端口
- **HTTP 服务自动识别**：检测真实网页内容（支持 HTML/JSON/XML 等）
- **进程分类与过滤**：
  - 🟢 用户应用（User）- 您的开发项目
  - 🔵 系统服务（System）- 操作系统和驱动服务
  - 🟣 创意软件（Creative）- Blender、Houdini、Nuke 等
  - 🟠 网络工具（Network）- Clash、V2Ray、代理软件
- **安全评估徽章**：每个进程显示安全等级和功能描述
- **多端口展示**：清晰显示同一进程监听的所有端口

### 📊 实时控制台日志
- 每个项目的控制台输出重定向至 `logs/{project_id}.log`
- 免刷新实时滚动日志查看，支持一键清除/复制

### 🔒 活动端口扫描与安全防护
- 扫描所有 TCP LISTENING 端口及对应进程
- 智能安全评级：安全 / 警告 / 极危
- 高危安全锁：锁定状态拦截危险操作，解锁后仍有二次确认
- 系统进程硬核强锁保护（Windows/Linux/macOS 各平台关键进程）

### 📈 系统监控看板
- 实时 CPU / 内存负载条
- 主机 IP、运行时间
- 动态操作系统检测（自动显示 Windows/Linux/macOS）

### 🎨 界面特性
- **自动刷新开关**：3秒间隔轮询，可随时暂停节省资源
- **跨平台 Tailwind CSS**：本地静态文件，无需 CDN，离线可用
- **动态 CORS 配置**：自动放行当前监听端口的跨域请求
- **分类过滤**：快速筛选不同类型的进程

---

## 跨平台支持

| 平台 | 支持状态 | 说明 |
|------|---------|------|
| **Windows** | ✅ 完整支持 | 原生环境，使用 `taskkill` 和 `netstat -ano` |
| **Linux** | ✅ 完整支持 | 使用 `kill -9` 和 `netstat -tlnp` |
| **macOS** | ✅ 完整支持 | 使用 `kill -9` 和 `netstat -lnp` |

### 跨平台特性
- 动态平台检测（`sys.platform`）
- 平台特定命令解析（`shlex` 参数自动调整）
- 进程保护列表适配各平台关键进程
- 跨平台路径处理（`\\` 和 `/`）

---

## 部署

### 环境要求

- Python 3.11+
- 依赖：`fastapi`, `uvicorn`, `psutil`

### 安装

**Windows:**
```bash
cd G:\AITools\portdashboard
python -m venv .venv
.venv\Scripts\pip install fastapi uvicorn psutil
```

**Linux / macOS:**
```bash
cd ~/portdashboard
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn psutil
```

### 启动

**Windows:**
双击 `start.bat` 或在终端运行：
```bash
start.bat          # 稳定模式
start.bat dev      # 开发模式（热重载）
```

**Linux / macOS:**
```bash
./start.sh         # 稳定模式
./start.sh dev     # 开发模式（热重载）
```

访问 http://localhost:9229/

### 开机自启（可选）

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

## 项目结构

```
portdashboard/
├── app.py                    # FastAPI 后端（跨平台支持）
├── start.bat                 # Windows 启动脚本
├── start.sh                  # Linux/macOS 启动脚本
├── projects.json             # 托管项目配置（数据文件）
├── running_pids.json         # 运行中 PID 缓存
├── templates/
│   └── index.html            # 前端界面（Vue 3 + Tailwind CSS）
├── static/
│   └── tailwind.min.css      # 本地 Tailwind CSS（离线可用）
├── logs/
│   └── *.log                 # 各项目的运行日志
└── agent-harness/            # CLI 工具和测试
    ├── CLI_HELP.html         # CLI 帮助文档（中英文双语）
    ├── cli_anything/
    │   └── portdashboard/    # CLI 客户端实现
    └── skills/
        └── cli-anything-portdashboard/
```

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/system/stats` | GET | 获取系统统计信息（CPU、内存、IP、运行时间） |
| `/api/system/ports` | GET | 获取所有活动端口列表 |
| `/api/system/ports/kill/<pid>` | POST | 终止指定 PID 的进程 |
| `/api/dashboard/snapshot` | GET | 获取完整仪表板快照 |
| `/api/projects` | GET | 获取托管项目列表 |
| `/api/projects` | POST | 创建新项目 |
| `/api/projects/<id>` | PUT | 更新项目配置 |
| `/api/projects/<id>` | DELETE | 删除项目 |
| `/api/projects/<id>/start` | POST | 启动项目 |
| `/api/projects/<id>/stop` | POST | 停止项目 |
| `/api/projects/<id>/logs` | GET | 获取项目日志 |
| `/api/projects/<id>/logs/clear` | POST | 清除项目日志 |

---

## 许可证

MIT License
