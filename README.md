# PORT DASHBOARD - 本地网页与应用端口控制中心

这是一个专为 WSL（Windows Subsystem for Linux）环境设计的本地网页服务及端口控制面板。UI 风格完美致敬了 **Hermes Official Dashboard** 的赛博朋克极客美学，提供了一套深绿（Deep Teal）与奶油白（Cream Accent）高对比度结合、并伴有温暖黄光（Warm Ambient Glow）的高颜值监控界面。

## 🌟 核心功能

1. **托管项目生命周期一键控制**：
   - 自由创建、编辑、删除您本地开发的网页项目（如 Vite、React、Vue、Python FastAPI、Node 等）。
   - 一键**启动**与**关闭**。关闭时使用 Linux 进程组（Process Group PGID）机制，能够连同 `npm run dev` 启动的子 `node` 进程等深度依赖树一起彻底终止，完美杜绝端口残留和孤儿进程。
   - 自动持久化保存项目配置到本地 `projects.json`。
   - 断电重新托管：如果面板重启，它能自动通过 PID 重合算法找回并重新接管此前由面板启动的进程！

2. **实时控制台日志流监听**：
   - 每个项目启动时，其全部控制台输出（Standard Out & Error）会被管道重定向至 `logs/{project_id}.log` 中。
   - 点击卡片上的 **日志 (Logs)**，即可在右侧类似 CRT 终端的绿色荧光代码块中**实时、免刷新**滚动监听该网页的控制台报错和输出。
   - 支持一键清除日志、一键复制全部日志。

3. **全局活动端口进程扫描与强杀**：
   - 实时调用 Linux 内核 `ss -ltnp` 扫描当前 WSL 实例内**所有正在监听的 TCP 端口**。
   - 展示每个监听端口所绑定的地址、对应的运行进程名称、以及操作系统 PID。
   - **一键导入托管**：看到某个端口已经在外面开着了？点击 “导入托管” 按钮，一键把该端口信息导入，免去手动输入端口的繁琐。
   - **一键强杀进程**：如果某个端口被死锁或有残留服务，点击 “强杀 (Kill)” 即可直接干掉它。

4. **系统核心指标监控看板**：
   - 顶部提供极其炫酷的 WSL 主机 IP 地址、实时 CPU 负载条、RAM 内存负载条和系统启动运行时间（Uptime）。

---

## 🚀 快速启动

控制中心没有任何繁杂的外部依赖，纯原生 Python + HTML 单文件 SPA 实现。

在当前目录（`/mnt/g/AITOOLS/mydashboard`）下，直接运行附带的启动脚本：

```bash
./start.sh
```

### 访问面板

打开您的 Windows 浏览器，直接输入以下任一地址即可进入极帅控制台：

- 本地回路地址：`http://localhost:9229/`
- WSL 局域网地址：`http://<您的WSL-IP>:9229/`（可以在运行 `start.sh` 时在屏幕上直接看到该 IP）

---

## 📂 项目结构

```text
mydashboard/
├── app.py              # FastAPI 后端服务器 (进程管理 API & 静态 UI 路由)
├── start.sh            # 自动化环境检查与高能启动脚本
├── projects.json       # 托管项目配置存储 (已预置 Hermes 官方 WebUI 示例)
├── running_pids.json   # 进程恢复映射状态
├── README.md           # 说明文档 (本文件)
├── templates/
│   └── index.html      # 核心 UI 界面 (Vue 3 响应式渲染 + Tailwind CSS)
└── logs/
    └── *.log           # 各个托管网页的实时运行控制台日志文件
```

Enjoy your premium Hermes-style Web Dev experience! 🚀
