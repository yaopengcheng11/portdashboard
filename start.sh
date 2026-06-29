#!/bin/bash
# Port Dashboard 启动脚本 (Linux/macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install fastapi uvicorn psutil
else
    source .venv/bin/activate
fi

# Set environment variables
export PYTHONUNBUFFERED=1
export FORCE_COLOR=1

# Check for reload mode
if [ "$1" = "--reload" ]; then
    echo "Starting Port Dashboard in reload mode..."
    uvicorn app:app --host 0.0.0.0 --port 9229 --reload
else
    echo "Starting Port Dashboard..."
    uvicorn app:app --host 0.0.0.0 --port 9229
fi
