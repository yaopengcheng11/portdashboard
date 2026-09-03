"""port_parser — 平台相关的监听端口枚举。

从 app.py 拆出，每个 helper 只负责一个平台的怪癖，便于单独测试。
Windows 走 ``netstat -ano`` 文本解析；macOS / Linux 逐进程枚举
（见 ``_listening_from_psutil_procs`` 里为何不用 netstat）。

Public surface:
    build_pid_name_map()  -> Dict[int, str]
    parse_listening_ports(pid_to_name)  -> List[dict]
    format_addr(ip, port)  -> str
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from typing import Dict, List

# 与 app.py 保持一致（此处不 import app，避免循环依赖）
IS_WINDOWS = sys.platform == "win32"

_SUBPROCESS_TIMEOUT = 3.0


def _console_encoding() -> str:
    """tasklist/netstat 输出用的是 OEM 代码页：中文 Windows 是 GBK/CP936，
    按 utf-8 解码会把非 ASCII 进程名吃掉（errors='ignore' 静默丢字节）。"""
    return "mbcs" if IS_WINDOWS else "utf-8"


def build_pid_name_map() -> Dict[int, str]:
    """Return ``{pid: process_name}`` for the current OS.

    On Windows, parses ``tasklist /FO CSV /NH`` output. On Linux/macOS,
    walks ``psutil.process_iter`` (cheaper than spawning ``ps``).
    """
    if IS_WINDOWS:
        return _pid_map_from_tasklist()
    return _pid_map_from_psutil()


def _pid_map_from_tasklist() -> Dict[int, str]:
    """Parse Windows ``tasklist`` CSV output into a pid -> name dict."""
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        timeout=_SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        return {}
    pid_to_name: Dict[int, str] = {}
    reader = csv.reader(io.StringIO(result.stdout))
    for row in reader:
        if len(row) < 2:
            continue
        try:
            pid_to_name[int(row[1])] = row[0]
        except ValueError:
            # Second column wasn't a PID — skip this row.
            continue
    return pid_to_name


def _pid_map_from_psutil() -> Dict[int, str]:
    """Linux/macOS: use psutil to walk the process table (no subprocess)."""
    import psutil  # local import — only on non-Windows
    pid_to_name: Dict[int, str] = {}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid_to_name[proc.info["pid"]] = proc.info["name"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pid_to_name


def parse_listening_ports(pid_to_name: Dict[int, str]) -> List[dict]:
    """Return LISTENING ports for the current OS.

    Output shape (one dict per port):
        ``{"address": "0.0.0.0:3000", "port": 3000, "process": "node",
           "pid": 12345, "status": "listening", "platform": "linux"}``

    Duplicates are deduped by port number — the first match wins.
    """
    if IS_WINDOWS:
        return _parse_windows_listening(pid_to_name)
    return _listening_from_psutil_procs()


def _parse_windows_listening(pid_to_name: Dict[int, str]) -> List[dict]:
    """Parse ``netstat -ano`` output (Windows)."""
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        timeout=_SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        return []

    ports: List[dict] = []
    seen_ports: set = set()
    for line in result.stdout.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        pid_str = parts[4]
        port_match = re.search(r":(\d+)$", local_addr)
        if not port_match:
            continue
        port = int(port_match.group(1))
        if port in seen_ports:
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            pid = None
        proc_name = pid_to_name.get(pid, "Unknown") if pid else "Unknown"
        ports.append(
            {
                "address": local_addr,
                "port": port,
                "process": proc_name,
                "pid": pid,
                "status": "listening",
                "platform": sys.platform,
            }
        )
        seen_ports.add(port)
    return ports


def format_addr(ip: str, port: int) -> str:
    """``127.0.0.1:3000`` / ``[::1]:3000``. 括号避免 ``::1:3000`` 的歧义。"""
    if ip and ":" in ip:
        return f"[{ip}]:{port}"
    return f"{ip or '*'}:{port}"


def _listening_from_psutil_procs(proc_iter=None) -> List[dict]:
    """macOS / Linux：逐进程枚举 LISTEN 连接。

    这是 ``psutil.net_connections()`` 系统级调用失败时的回退路径 ——
    在 macOS 上它需要 root，总是抛 AccessDenied。

    刻意不走 netstat：macOS 的 ``netstat`` 里 ``-p`` 是 protocol 而非
    "show PID" 且需要参数（``netstat -lnp`` 直接以 64 退出），地址与端口用
    ``.`` 而非 ``:`` 分隔，而且根本没有 PID 列 —— 三者叠加使文本解析
    在 macOS 上不可能得到任何结果。逐进程枚举没有子进程、没有正则、
    也没有 locale 与输出格式漂移的风险。

    ``proc_iter`` 仅供测试注入，从而不依赖真机进程表。
    """
    import psutil  # local import — 与 _pid_map_from_psutil 保持一致

    if proc_iter is None:
        proc_iter = psutil.process_iter(["pid", "name"])

    ports: List[dict] = []
    seen_ports: set = set()
    for proc in proc_iter:
        try:
            conns = proc.net_connections(kind="tcp")
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            # 非当前用户拥有的进程看不到，属正常（实测约四成会拒绝）
            continue
        except Exception:
            continue
        for conn in conns:
            if conn.status != "LISTEN":
                continue
            laddr = getattr(conn, "laddr", None)
            port = getattr(laddr, "port", None)
            if not port or port in seen_ports:
                continue
            try:
                name = proc.info.get("name") or "Unknown"
                pid = proc.info.get("pid")
            except (AttributeError, psutil.NoSuchProcess):
                name, pid = "Unknown", None
            ports.append(
                {
                    "address": format_addr(getattr(laddr, "ip", ""), port),
                    "port": port,
                    "process": name,
                    "pid": pid,
                    "status": "listening",
                    "platform": sys.platform,
                }
            )
            seen_ports.add(port)
    return ports