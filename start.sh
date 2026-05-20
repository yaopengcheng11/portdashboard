#!/bin/bash

# Define colors for CLI output
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}             P O R T   D A S H B O A R D${NC}"
echo -e "${CYAN}======================================================${NC}"
echo -e "正在初始化端口控制中心..."

# 1. Detect which Python interpreter has fastapi & uvicorn installed
PYTHON_EXE=""

if python3 -c "import fastapi, uvicorn" 2>/dev/null; then
    PYTHON_EXE="python3"
elif [ -f "/home/yaopc/.hermes/hermes-agent/venv/bin/python3" ]; then
    # Fallback to the Hermes Agent virtualenv which we verified has fastapi & uvicorn
    PYTHON_EXE="/home/yaopc/.hermes/hermes-agent/venv/bin/python3"
fi

if [ -z "$PYTHON_EXE" ]; then
    echo -e "${YELLOW}警告: 未在当前环境检测到 fastapi 或 uvicorn。正在尝试自动为您安装...${NC}"
    python3 -m pip install fastapi uvicorn
    if [ $? -eq 0 ]; then
        PYTHON_EXE="python3"
    else
        echo -e "${RED}错误: 安装失败，请先手动运行: pip install fastapi uvicorn${NC}"
        exit 1
    fi
fi

# 2. Get local IP address for easy access
IP_ADDR=$(hostname -I | awk '{print $1}')
if [ -z "$IP_ADDR" ]; then
    IP_ADDR="127.0.0.1"
fi

echo -e "${GREEN}✓ 环境检测成功！${NC}"
echo -e "使用 Python 执行器: ${YELLOW}$PYTHON_EXE${NC}"
echo -e "控制台访问地址 (Windows 浏览器直接输入打开):"
echo -e "  - 本地回环: ${GREEN}http://localhost:9229/${NC}"
echo -e "  - 局域网/WSL: ${GREEN}http://$IP_ADDR:9229/${NC}"
echo -e "------------------------------------------------------"
echo -e "按下 ${YELLOW}Ctrl+C${NC} 可停止控制中心服务。"
echo ""

# 3. Start the server
cd "$(dirname "$0")"
$PYTHON_EXE app.py
