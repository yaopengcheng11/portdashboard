# PORT DASHBOARD - 本地网页与应用端口控制中心 🎛️

这是一个专为 **WSL (Windows Subsystem for Linux)** 环境设计的本地网页服务及端口控制面板。UI 风格完美致敬了 **Hermes Official Dashboard** 的赛博朋克极客美学，提供了一套深绿 (Deep Teal) 与奶油白 (Cream Accent) 高对比度结合、并伴有温暖黄光 (Warm Ambient Glow) 的高颜值、免刷新监控界面。

---

## 🌟 核心功能

1. **托管项目生命周期一键控制**：
   - 自由创建、编辑、删除您本地开发的网页项目（如 Vite、React、Vue、Python FastAPI、Django、Node 等）。
   - 一键**启动**与**关闭**。关闭时使用 Linux 进程组（Process Group PGID）机制，能够连同 `npm run dev` 启动的子 `node` 进程等深度依赖树一起彻底终止，**100% 解决 WSL 端口残留和死锁问题**！
   - 自动持久化保存项目配置到本地 `projects.json`。
   - **断电重新托管**：如果面板重启，它能自动通过 PID 活跃比对，自动重新找回接管此前由面板启动的进程！
   - **外部运行识别**：如果某个端口已经被外部进程占用，控制台会将其标记为 `外部运行中`，允许直接访问页面，但不会误判为可重复启动的托管实例。
   - **可选自动同步项目名称**：可按项目目录自动推断显示名，优先读取 `package.json` 的 `productName/name`、`pyproject.toml` 的项目名，读不到时回退为目录名，适合项目经常改名的场景。

2. **实时控制台日志流监听**：
   - 每个项目启动时，其全部控制台输出（Standard Out & Error）会被管道重定向至 `logs/{project_id}.log` 中。
   - 点击卡片上的 **日志 (Logs)**，即可在右侧类似 CRT 终端的绿色荧光代码块中**实时、免刷新、自动向下翻滚**监听该网页的控制台报错和输出。
   - 支持一键清除日志文件、一键复制全部日志。

3. **双端活动端口扫描与智能高危防护 (WSL + Windows Host)**：
   - **双端网络融合扫描**：不仅抓取 WSL 内部端口，还能跨界调用 Windows 的 `netstat.exe` 与 `tasklist.exe` 实时、免刷新扫描 Windows 宿主机上所有处于监听状态的 TCP 端口和进程，并以 `[Win]` 前缀呈现，打破系统壁垒。
   - **智能安全评级与功能字典**：自动识别端口功能，智能归类为 `🟢 安全`、`🟡 警告`、`🔴 极危` 三个安全评级，自带高频网络协议（如 SMB, RPC, DNS, MySQL, Redis, Ollama, Vite 等）详细语义说明，鼠标悬浮即可查看大字报浮窗释义。
   - **安全等级分流滤网**：表格上方集成响应式按钮组，支持一键按等级快速过滤，按钮实时展示当前分类下的活动进程总数，告别信息洪流。
   - **高危操作双保险安全锁**：页面正上方配有极客美学设计的 `高危安全锁` 控制闸。
     - **锁定状态（默认，安全模式）**：彻底锁定警告级高危操作。点击强杀警告级进程（如数据库）或对其执行导入托管，操作将被强力拦截并弹窗引导。
     - **解锁状态（高危允许）**：允许强杀与托管，但执行时依然会弹出醒目的二次风险告知对话框，杜绝手抖。
     - **极危进程硬核强锁**：对于系统内核级服务进程（如 `svchost.exe`, `System`, `lsass.exe`, `init`），面板**不展示“强杀”与“导入托管”按钮**，并显示 `🔒 系统强锁保护` 闪烁徽章，从根本上保证操作系统 100% 稳定，永不蓝屏！

4. **系统核心指标监控看板**：
   - 顶部提供极其炫酷的 WSL 主机 IP 地址、实时 CPU 负载条、RAM 内存负载条和系统启动运行时间（Uptime）。

5. **更稳的运行模式切换**：
   - 默认以**稳定模式**启动，关闭 `uvicorn --reload`，避免后台运行时因为扫描或文件落盘触发自重启。
   - 如需开发调试，可执行 `./start.sh dev` 进入**开发模式**，显式开启热重载。

---

## 🚀 部署与启动指南

控制中心没有任何繁杂的外部依赖，纯原生 Python + HTML 单文件 SPA 实现。

### A. 本地标准直接启动
在工作目录下，直接运行自适应环境寻址脚本：

```bash
chmod +x start.sh
./start.sh
```

如需前端模板热更新开发模式：

```bash
./start.sh dev
```

#### 访问面板
打开您的 Windows 浏览器，输入以下任一地址即可进入控制台：
- **本地回路（推荐）**：`http://localhost:9229/`
- **WSL 专属局域网地址**：`http://<您的WSL-IP>:9229/` （启动脚本屏幕上会高亮高亮显示该 IP）

---

### B. 开机自动后台无头运行部署 (Linux/WSL)

如果您希望这个端口控制中心在 WSL 每次启动时，自动在后台静默运行，无需手动打开终端启动：

#### 方法一：使用 PM2 后台守护（首选）
如果您本地安装了 NodeJS，使用 PM2 守护是最轻量级的方式：

```bash
# 使用 pm2 守护 python 后台，并命名为 app-port-dashboard
pm2 start app.py --name "app-port-dashboard" --interpreter python3
pm2 save
```

#### 方法二：配置 Linux Systemd 用户级系统服务（最推荐，免 Sudo、防输入密码阻碍自启）
在 WSL 的 Ubuntu 实例中，采用 **Systemd User Service (用户级系统服务)** 是最完美、最安全的开机自启方式。它完全以您当前的用户身份在后台运行，既不需要管理员权限，又不会在开机时因为需要输入 Sudo 密码而导致自启死锁。

创建并编辑用户服务文件：`~/.config/systemd/user/mydashboard.service`：

```ini
[Unit]
Description=My App Port Control Console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/mnt/g/AITOOLS/mydashboard
ExecStart=/home/yaopc/.hermes/hermes-agent/venv/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

配置完成后，**完全无需 sudo**，在当前普通用户终端执行以下命令即可立刻生效并完成开机自启绑定：

```bash
# 重载用户 Systemd 配置
systemctl --user daemon-reload

# 启用并立即启动服务
systemctl --user enable --now mydashboard

# 查看运行状态
systemctl --user status mydashboard
```

---

## 📂 项目结构

```text
mydashboard/
├── app.py              # FastAPI 核心后端 (系统指标统计、ss端口进程提取、进程树级控制 API)
├── start.sh            # 自适应 Python 环境寻址与多色亮色打印启动脚本
├── projects.json       # 项目托管配置存储 (数据文件)
├── running_pids.json   # 缓存运行中 PID，确保控制台崩溃重启后依然可找回托管
├── README.html         # HTML 版极帅官方说明手册 (双击在浏览器中直接打开)
├── README.md           # Markdown 简洁说明文档 (本文件)
├── templates/
│   └── index.html      # 核心 UI 界面 (Vue 3 响应式渲染 + Tailwind CSS)
└── logs/
    └── *.log           # 各个托管网页的实时运行控制台重定向日志文件
```

Enjoy your premium Web Dev experience with Port Dashboard! 🚀

---

## 补充说明

- `projects.json` 是托管项目配置源，卡片标题默认直接来自其中的 `name` 字段。
- 当某个项目启用 `sync_name: true` 后，前端显示名会在刷新快照时根据项目目录自动重算，不再完全依赖手填名称。
- `.gitignore` 默认忽略 `logs/*.log` 与 `running_pids.json`，这些运行期产物不会进入版本库。
