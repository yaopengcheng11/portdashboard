#!/bin/bash
# Port Dashboard 启动脚本 (Linux/macOS)
#
# 绑定地址与端口由 app.py 自己解析（与 start.bat / python app.py 完全一致）：
#   - 默认只绑 127.0.0.1，需要局域网访问时显式 MYDASHBOARD_HOST=0.0.0.0
#   - 端口取 MYDASHBOARD_PORT > mydashboard-config.json > 9229
# 不要在这里直接调 uvicorn —— 会绕过上述安全默认。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Set environment variables
export PYTHONUNBUFFERED=1
export FORCE_COLOR=1

# dev 模式 = 热重载（与 start.bat 的 dev 参数一致；--reload 保留兼容旧用法）
if [ "$1" = "dev" ] || [ "$1" = "--reload" ]; then
    export PORT_DASHBOARD_RELOAD=1
    echo "Starting Port Dashboard (dev mode, hot reload ON)..."
else
    echo "Starting Port Dashboard..."
fi

exec python3 app.py
