# Port Dashboard - 本地端口控制中心

本地网页服务及端口监控面板，运行于 Windows 原生环境。提供深绿与奶油白高对比度赛博朋克风格界面，免刷新实时监控。

---

## 核心功能

1. **项目生命周期一键控制**
   - 创建、编辑、删除托管项目（Vite、React、Python FastAPI、Node 等）
   - 一键启动/关闭，使用 `taskkill /T` 终止整棵进程树
   - 断电重启后自动通过 PID 重新接管之前由面板启动的进程
   - 外部运行识别：端口被外部进程占用时标记为"外部运行中"
   - 可选自动同步项目名称（读取 `package.json` / `pyproject.toml`）

2. **实时控制台日志**
   - 每个项目的控制台输出重定向至 `logs/{project_id}.log`
   - 免刷新实时滚动日志查看，支持一键清除/复制

3. **活动端口扫描与安全防护**
   - 扫描所有 TCP LISTENING 端口及对应进程
   - 智能安全评级：安全 / 警告 / 极危
   - 高危安全锁：锁定状态拦截危险操作，解锁后仍有二次确认
   - 系统进程硬核强锁保护

4. **系统监控看板**
   - 实时 CPU / 内存负载条
   - 主机 IP、运行时间

---

## 部署

### 环境要求

- Python 3.11+
- 依赖：`fastapi`, `uvicorn`, `psutil`

### 安装

```bash
cd G:\AITools\portdashboard
python -m venv .venv
.venv\Scripts\pip install fastapi uvicorn psutil
```

### 启动

双击 `start.bat` 或在终端运行：

```bash
start.bat          # 稳定模式
start.bat dev      # 开发模式（热重载）
```

访问 http://localhost:9229/

### 开机自启（可选）

使用 Windows Task Scheduler：

1. 打开"任务计划程序" → 创建基本任务
2. 触发器：用户登录时
3. 操作：启动程序
   - 程序：`G:\AITools\portdashboard\.venv\Scripts\pythonw.exe`
   - 参数：`app.py`
   - 起始于：`G:\AITools\portdashboard`

---

## 项目结构

```
portdashboard/
├── app.py              # FastAPI 后端（端口扫描、进程管理、系统监控 API）
├── start.bat           # Windows 启动脚本
├── projects.json       # 托管项目配置（数据文件）
├── running_pids.json   # 运行中 PID 缓存
├── templates/
│   └── index.html      # 前端界面（Vue 3 + Tailwind CSS）
└── logs/
    └── *.log           # 各项目的运行日志
```
