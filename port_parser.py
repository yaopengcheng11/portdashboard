"""port_parser — Platform-specific port-listening parsers.

Split out of app.py to break up a 100+ line function (cognitive 97) into
focused helpers. Each helper owns ONE platform's netstat / process-listing
quirk so it can be unit-tested in isolation and extended without growing
the dispatcher.

Public surface:
    build_pid_name_map()  -> Dict[int, str]
    parse_listening_ports(pid_to_name)  -> List[dict]
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from typing import Dict, List

# Platform flags — duplicated from app.py so port_parser.py stays
# standalone (no circular import). Keep these in sync with app.py:28-30.
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"

_SUBPROCESS_TIMEOUT = 3.0


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
        encoding="utf-8",
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
    """Run ``netstat`` for the current OS and return LISTENING ports.

    Output shape (one dict per port):
        ``{"address": "0.0.0.0:3000", "port": 3000, "process": "node",
           "pid": 12345, "status": "listening", "platform": "linux"}``

    Duplicates are deduped by port number — the first match wins.
    """
    if IS_WINDOWS:
        return _parse_windows_listening(pid_to_name)
    return _parse_unix_listening(pid_to_name)


def _parse_windows_listening(pid_to_name: Dict[int, str]) -> List[dict]:
    """Parse ``netstat -ano`` output (Windows)."""
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        encoding="utf-8",
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


def _parse_unix_listening(pid_to_name: Dict[int, str]) -> List[dict]:
    """Parse ``netstat -tlnp`` (Linux) or ``netstat -lnp`` (macOS) output."""
    netstat_args = ["netstat", "-tlnp"] if IS_LINUX else ["netstat", "-lnp"]
    result = subprocess.run(
        netstat_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=_SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        return []

    ports: List[dict] = []
    seen_ports: set = set()
    for line in result.stdout.splitlines():
        # e.g.: tcp  0  0  0.0.0.0:3000  0.0.0.0:*  LISTEN  12345/node
        parts = line.split()
        if len(parts) < 6:
            continue
        local_addr = parts[3]
        pid_prog = parts[-1]
        port_match = re.search(r":(\d+)$", local_addr)
        if not port_match:
            continue
        port = int(port_match.group(1))
        if port in seen_ports:
            continue
        # Extract "pid/program" — netstat's last column on Linux/macOS.
        pid = None
        proc_name = "Unknown"
        pid_match = re.match(r"(\d+)/", pid_prog)
        if pid_match:
            pid = int(pid_match.group(1))
            proc_name = pid_to_name.get(pid, "Unknown")
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