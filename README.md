# PORT DASHBOARD - 本地网页与应用端口控制中心 🎛️

这是一个专为 **WSL (Windows Subsystem for Linux)** 环境设计的本地网页服务及端口控制面板。UI 风格完美致敬了 **Hermes Official Dashboard** 的赛博朋克极客美学，提供了一套深绿 (Deep Teal) 与奶油白 (Cream Accent) 高对比度结合、并伴有温暖黄光 (Warm Ambient Glow) 的高颜值、免刷新监控界面。

---

## 🌟 核心功能

1. **托管项目生命周期一键控制**：
   - 自由创建、编辑、删除您本地开发的网页项目（如 Vite、React、Vue、Python FastAPI、Django、Node 等）。
   - 一键**启动**与**关闭**。关闭时使用 Linux 进程组（Process Group PGID）机制，能够连同 `npm run dev` 启动的子 `node` 进程等深度依赖树一起彻底终止，**100% 解决 WSL 端口残留和死锁问题**！
   - 自动持久化保存项目配置到本地 `projects.json`。
   - **断电重新托管**：如果面板重启，它能自动通过 PID 活跃比对，自动重新找回接管此前由面板启动的进程！

2. **实时控制台日志流监听**：
   - 每个项目启动时，其全部控制台输出（Standard Out & Error）会被管道重定向至 `logs/{project_id}.log` 中。
   - 点击卡片上的 **日志 (Logs)**，即可在右侧类似 CRT 终端的绿色荧光代码块中**实时、免刷新、自动向下翻滚**监听该网页的控制台报错和输出。
   - 支持一键清除日志文件、一键复制全部日志。

3. **全局活动端口进程扫描与强杀**：
   - 实时调用 Linux 内核 `ss -ltnp` 扫描当前 WSL 实例内**所有正在监听的 TCP 端口**。
   - 展示每个监听端口所绑定的地址、对应的运行进程名称、以及操作系统 PID。
   - **一键导入托管**：看到某个端口已经在外面开着了？点击 “导入托管” 按钮，一键把该端口信息导入，免去手动输入端口的繁琐。
   - **一键强杀进程**：如果某个端口被死锁或有残留服务，点击 “强杀 (Kill)” 即可直接干掉它。

4. **系统核心指标监控看板**：
   - 顶部提供极其炫酷的 WSL 主机 IP 地址、实时 CPU 负载条、RAM 内存负载条和系统启动运行时间（Uptime）。

---

## 🚀 部署与启动指南

控制中心没有任何繁杂的外部依赖，纯原生 Python + HTML 单文件 SPA 实现。

### A. 本地标准直接启动
在工作目录下，直接运行自适应环境寻址脚本：

```bash
chmod +x start.sh
./start.sh
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

#### 方法二：配置 Linux Systemd 系统服务
在 WSL 的 Ubuntu 实例中（确保 `/etc/wsl.conf` 开启了 `systemd` 选项），您可以创建一个系统服务文件 `/etc/systemd/system/mydashboard.service`：

```ini
[Unit]
Description=My App Port Control Console
After=network.target

[Service]
Type=simple
User=yaopc
WorkingDirectory=/mnt/g/AITOOLS/mydashboard
ExecStart=/home/yaopc/.hermes/hermes-agent/venv/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

配置完成后，执行以下命令使服务生效，即可完成开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable mydashboard
sudo systemctl start mydashboard
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
