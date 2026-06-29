import csv
import io
import json
import os
import platform
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import concurrent.futures
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil
from fastapi import FastAPI, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

@asynccontextmanager
async def lifespan(app: FastAPI):
    readopt_processes()
    ensure_background_refresh_thread()
    invalidate_ports_cache()
    yield

app = FastAPI(title="MyDashboard - Port Control Center", lifespan=lifespan)


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """动态 CORS 中间件：自动检测系统活动端口并放行"""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")

        # 基础白名单
        allowed_origins = {
            "http://localhost:9229",
            "http://127.0.0.1:9229",
        }

        # 自动检测系统所有活动端口（使用缓存，3秒TTL）
        try:
            active_ports = get_active_system_ports()
            for port_info in active_ports:
                port = port_info.get("port")
                if port:
                    allowed_origins.add(f"http://localhost:{port}")
                    allowed_origins.add(f"http://127.0.0.1:{port}")
        except Exception:
            pass

        # 处理 preflight 请求
        if request.method == "OPTIONS":
            response = await call_next(request)
            if origin in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "*"
                response.headers["Access-Control-Allow-Credentials"] = "true"
            return response

        # 正常请求
        response = await call_next(request)
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


app.add_middleware(DynamicCORSMiddleware)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROJECTS_FILE = os.path.join(BASE_DIR, "projects.json")
RUNNING_PIDS_FILE = os.path.join(BASE_DIR, "running_pids.json")
PORTS_CACHE_TTL = 3.0
STATS_CACHE_TTL = 2.0
LOG_READ_CHUNK_SIZE = 64 * 1024
BACKGROUND_PORT_REFRESH_INTERVAL = 10.0

os.makedirs(LOGS_DIR, exist_ok=True)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ACTIVE_PROCESSES: Dict[str, subprocess.Popen] = {}
ACTIVE_LOG_FILES: Dict[str, io.IOBase] = {}
START_TIME = time.time()
PORTS_CACHE = {"timestamp": 0.0, "value": []}
STATS_CACHE = {"timestamp": 0.0, "value": {}}
PROJECTS_LOCK = threading.Lock()
PIDS_LOCK = threading.Lock()
PORTS_CACHE_LOCK = threading.Lock()
STATS_CACHE_LOCK = threading.Lock()
PORTS_REFRESH_THREAD_STARTED = False


class Project(BaseModel):
    id: str
    name: str
    cwd: str
    command: str
    port: int
    description: Optional[str] = ""
    sync_name: bool = False


def validate_project_id(project_id: str) -> str:
    if "/" in project_id or "\\" in project_id or ".." in project_id or not project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project ID: contains path traversal characters")
    return project_id


def atomic_write_json(path: str, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def normalize_pid_registry(raw: dict) -> dict:
    normalized = {}
    for project_id, value in raw.items():
        if isinstance(value, int):
            normalized[project_id] = {
                "pid": value,
                "managed": True,
                "started_at": None,
            }
        elif isinstance(value, dict) and isinstance(value.get("pid"), int):
            normalized[project_id] = {
                "pid": value["pid"],
                "managed": bool(value.get("managed", True)),
                "started_at": value.get("started_at"),
            }
    return normalized


def load_projects() -> List[dict]:
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with PROJECTS_LOCK:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []


def save_projects(projects: List[dict]):
    with PROJECTS_LOCK:
        atomic_write_json(PROJECTS_FILE, projects)


def infer_project_display_name(cwd: str) -> Optional[str]:
    base_path = Path(cwd)
    if not base_path.is_dir():
        return None

    package_json = base_path / "package.json"
    if package_json.is_file():
        try:
            with package_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            name = (data.get("productName") or data.get("name") or "").strip()
            if name:
                return name
        except Exception:
            pass

    pyproject_toml = base_path / "pyproject.toml"
    if pyproject_toml.is_file():
        try:
            import tomllib

            with pyproject_toml.open("rb") as f:
                data = tomllib.load(f)
            project = data.get("project") or {}
            poetry = (data.get("tool") or {}).get("poetry") or {}
            name = (project.get("name") or poetry.get("name") or "").strip()
            if name:
                return name
        except Exception:
            pass

    return base_path.name or None


def apply_project_display_name(project: dict) -> dict:
    normalized = dict(project)
    normalized["sync_name"] = bool(normalized.get("sync_name", False))
    if normalized["sync_name"]:
        inferred_name = infer_project_display_name(normalized.get("cwd", ""))
        if inferred_name:
            normalized["name"] = inferred_name
    return normalized


def load_running_pids() -> dict:
    if not os.path.exists(RUNNING_PIDS_FILE):
        return {}
    try:
        with PIDS_LOCK:
            with open(RUNNING_PIDS_FILE, "r", encoding="utf-8") as f:
                return normalize_pid_registry(json.load(f))
    except Exception:
        return {}


def save_running_pids(pids: dict):
    with PIDS_LOCK:
        atomic_write_json(RUNNING_PIDS_FILE, pids)


def is_pid_running(pid: int) -> bool:
    return psutil.pid_exists(pid)


def parse_listening_ports() -> List[dict]:
    ports_info = []
    seen_ports = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != "LISTEN":
                continue
            port = conn.laddr.port
            if port in seen_ports:
                continue
            pid = conn.pid
            proc_name = "Unknown"
            project_name = ""
            if pid:
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name()
                    # Try to infer project name from working directory
                    try:
                        cwd = proc.cwd()
                        inferred = infer_project_display_name(cwd)
                        if inferred:
                            project_name = inferred
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            ports_info.append({
                "address": f"{conn.laddr.ip}:{port}",
                "port": port,
                "process": proc_name,
                "pid": pid,
                "status": "listening",
                "platform": sys.platform,
                "project_name": project_name,
            })
            seen_ports.add(port)
    except (psutil.AccessDenied, OSError) as e:
        print(f"Error parsing ports (psutil): {e}, falling back to netstat")
        ports_info = _parse_ports_netstat()
    return ports_info


def _parse_ports_netstat() -> List[dict]:
    """Fallback port scanner using netstat when psutil lacks permissions."""
    ports_info = []
    seen_ports = set()
    try:
        pid_to_name = {}

        # Build PID-to-name mapping (platform-specific)
        if IS_WINDOWS:
            tasklist_result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=3.0
            )
            if tasklist_result.returncode == 0:
                reader = csv.reader(io.StringIO(tasklist_result.stdout))
                for row in reader:
                    if len(row) >= 2:
                        try:
                            pid_to_name[int(row[1])] = row[0]
                        except ValueError:
                            pass
        else:
            # Linux/macOS: read from psutil
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pid_to_name[proc.info['pid']] = proc.info['name']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        # Run netstat (platform-specific flags)
        if IS_WINDOWS:
            netstat_result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=3.0
            )
            if netstat_result.returncode != 0:
                return ports_info
            for line in netstat_result.stdout.strip().splitlines():
                if "LISTENING" not in line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                local_addr = parts[1]
                pid_str = parts[4]
                port_match = re.search(r':(\d+)$', local_addr)
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
                ports_info.append({
                    "address": local_addr,
                    "port": port,
                    "process": proc_name,
                    "pid": pid,
                    "status": "listening",
                    "platform": sys.platform,
                })
                seen_ports.add(port)
        else:
            # Linux/macOS: use -tlnp (Linux) or -lnp (macOS)
            netstat_args = ["netstat", "-tlnp"] if IS_LINUX else ["netstat", "-lnp"]
            netstat_result = subprocess.run(
                netstat_args,
                capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=3.0
            )
            if netstat_result.returncode != 0:
                return ports_info
            for line in netstat_result.stdout.strip().splitlines():
                # Parse lines like: tcp  0  0  0.0.0.0:3000  0.0.0.0:*  LISTEN  12345/node
                parts = line.split()
                if len(parts) < 6:
                    continue
                local_addr = parts[3]
                pid_prog = parts[-1] if IS_LINUX else parts[-1]
                port_match = re.search(r':(\d+)$', local_addr)
                if not port_match:
                    continue
                port = int(port_match.group(1))
                if port in seen_ports:
                    continue
                # Extract PID from "pid/program" format
                pid = None
                proc_name = "Unknown"
                pid_match = re.match(r'(\d+)/', pid_prog)
                if pid_match:
                    pid = int(pid_match.group(1))
                    proc_name = pid_to_name.get(pid, "Unknown")
                ports_info.append({
                    "address": local_addr,
                    "port": port,
                    "process": proc_name,
                    "pid": pid,
                    "status": "listening",
                    "platform": sys.platform,
                })
                seen_ports.add(port)
    except Exception as e:
        print(f"Error parsing ports (netstat fallback): {e}")
    return ports_info


def get_active_system_ports(force_refresh: bool = False) -> List[dict]:
    now = time.time()
    with PORTS_CACHE_LOCK:
        if not force_refresh and now - PORTS_CACHE["timestamp"] < PORTS_CACHE_TTL:
            return list(PORTS_CACHE["value"])

    ports_info = parse_listening_ports()
    ports_info.sort(key=lambda x: x["port"])
    with PORTS_CACHE_LOCK:
        PORTS_CACHE["timestamp"] = time.time()
        PORTS_CACHE["value"] = ports_info
        return list(PORTS_CACHE["value"])


def invalidate_ports_cache():
    with PORTS_CACHE_LOCK:
        PORTS_CACHE["timestamp"] = 0.0


def background_refresh_ports_cache():
    while True:
        try:
            get_active_system_ports(force_refresh=True)
        except Exception as e:
            print(f"Background port refresh error: {e}")
        time.sleep(BACKGROUND_PORT_REFRESH_INTERVAL)


def ensure_background_refresh_thread():
    global PORTS_REFRESH_THREAD_STARTED
    if PORTS_REFRESH_THREAD_STARTED:
        return
    thread = threading.Thread(target=background_refresh_ports_cache, daemon=True, name="ports-cache-refresh")
    thread.start()
    PORTS_REFRESH_THREAD_STARTED = True


def cleanup_stale_process_tracking(project_id: str, pids_map: Optional[dict] = None):
    if project_id in ACTIVE_PROCESSES and ACTIVE_PROCESSES[project_id].poll() is not None:
        ACTIVE_PROCESSES.pop(project_id, None)
    if pids_map is None:
        pids_map = load_running_pids()
    entry = pids_map.get(project_id)
    if entry and not is_pid_running(entry["pid"]):
        pids_map.pop(project_id, None)
        save_running_pids(pids_map)


def readopt_processes():
    pids_map = load_running_pids()
    updated_pids_map = {}
    for proj_id, entry in pids_map.items():
        pid = entry["pid"]
        if is_pid_running(pid):
            updated_pids_map[proj_id] = entry
            print(f"Re-adopted running project {proj_id} with PID {pid}")
        else:
            print(f"Project {proj_id} with PID {pid} is no longer running")
    save_running_pids(updated_pids_map)


def get_system_stats_snapshot(force_refresh: bool = False) -> dict:
    now = time.time()
    with STATS_CACHE_LOCK:
        if not force_refresh and now - STATS_CACHE["timestamp"] < STATS_CACHE_TTL and STATS_CACHE["value"]:
            return STATS_CACHE["value"]

    cpu_usage = psutil.cpu_percent(interval=None)

    mem = psutil.virtual_memory()
    mem_percent = round(mem.percent, 1)
    mem_total_gb = round(mem.total / (1024 ** 3), 1)
    mem_used_gb = round(mem.used / (1024 ** 3), 1)

    try:
        ip_address = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip_address = "127.0.0.1"

    uptime_sec = time.time() - START_TIME
    if uptime_sec < 60:
        uptime_str = f"{int(uptime_sec)}s"
    elif uptime_sec < 3600:
        uptime_str = f"{int(uptime_sec // 60)}m {int(uptime_sec % 60)}s"
    else:
        uptime_str = f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m"

    snapshot = {
        "cpu_percent": cpu_usage,
        "memory": {
            "percent": mem_percent,
            "total_gb": mem_total_gb,
            "used_gb": mem_used_gb,
        },
        "ip_address": ip_address,
        "uptime": uptime_str,
        "os": platform.system(),
    }
    with STATS_CACHE_LOCK:
        STATS_CACHE["timestamp"] = now
        STATS_CACHE["value"] = snapshot
    return snapshot


def get_project_runtime_state(project: dict, active_ports: List[dict], pids_map: dict) -> dict:
    project_id = project["id"]
    target_port = project["port"]
    cleanup_stale_process_tracking(project_id, pids_map)

    port_match = next((p for p in active_ports if p["port"] == target_port), None)
    status = "stopped"
    current_pid = None
    process_owner = "Unknown"
    managed = False

    proc = ACTIVE_PROCESSES.get(project_id)
    if proc and proc.poll() is None:
        status = "running"
        current_pid = proc.pid
        process_owner = "Dashboard"
        managed = True
    else:
        ACTIVE_PROCESSES.pop(project_id, None)
        entry = pids_map.get(project_id)
        if entry and is_pid_running(entry["pid"]):
            status = "running"
            current_pid = entry["pid"]
            process_owner = "Dashboard (Adopted)"
            managed = True
        elif entry:
            pids_map.pop(project_id, None)
            save_running_pids(pids_map)

    if status == "stopped" and port_match:
        status = "external"
        current_pid = port_match["pid"]
        process_owner = f"External ({port_match['process']})"

    return {
        **project,
        "status": status,
        "pid": current_pid,
        "owner": process_owner,
        "port_active": port_match is not None,
        "port_process": port_match,
        "managed": managed,
    }


def get_projects_snapshot(active_ports: Optional[List[dict]] = None) -> List[dict]:
    projects = [apply_project_display_name(project) for project in load_projects()]
    if active_ports is None:
        active_ports = get_active_system_ports()
    pids_map = load_running_pids()
    return [get_project_runtime_state(project, active_ports, pids_map) for project in projects]


def check_http_port(port: int, timeout: float = 1.5) -> bool:
    """Check if a port serves actual web content (not just HTTP protocol)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(('127.0.0.1', port))
        sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nAccept: text/html,application/json,*/*\r\nConnection: close\r\n\r\n")

        response = b""
        while True:
            try:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                response += chunk
                if len(response) > 65536:
                    break
            except socket.timeout:
                break
        sock.close()

        if not response.startswith(b"HTTP/"):
            return False

        # Split headers and body
        header_end = response.find(b"\r\n\r\n")
        if header_end == -1:
            return False

        headers_raw = response[:header_end].decode("utf-8", errors="ignore").lower()
        body = response[header_end + 4:]

        # Check status code - reject 4xx/5xx (no real web content)
        status_line = headers_raw.split("\r\n")[0]
        try:
            status_code = int(status_line.split(" ")[1])
            if status_code >= 400:
                return False
        except (IndexError, ValueError):
            return False

        # Check Content-Type for web content
        WEB_CONTENT_TYPES = ["text/html", "text/plain", "application/json", "application/xml", "application/javascript"]
        for content_type in WEB_CONTENT_TYPES:
            if content_type in headers_raw:
                return True

        # If no recognized content-type, check if body has HTML-like content
        body_text = body[:2048].decode("utf-8", errors="ignore")
        if "<html" in body_text.lower() or "<!doctype" in body_text.lower():
            return True

        return False
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return False


def categorize_process(process_name: str, ports: list) -> str:
    """Categorize a process into user-facing groups."""
    name = process_name.lower()
    # Strip .exe suffix for cross-platform compatibility
    name_no_ext = name.replace('.exe', '') if name.endswith('.exe') else name

    # System/vendor services: should not be stopped
    SYSTEM_PROCESSES = {
        # Windows
        'svchost.exe', 'csrss.exe', 'smss.exe', 'wininit.exe',
        'winlogon.exe', 'lsass.exe', 'services.exe',
        'vpnagent.exe', 'cer_service.exe', 'agentshell_guard.exe',
        'asus_framework.exe', 'rogiveservice.exe', 'armourycrate.service.exe',
        'rogliveservice.exe', 'alilangclient.exe',
        'system', 'idle', 'memory compression', 'registry',
        # Unix/macOS
        'init', 'systemd', 'launchd', 'kernel_task',
        'kthreadd', 'ksoftirqd', 'migration', 'kworker',
        'dbus-daemon', 'polkitd', 'networkmanager',
        'vpnagent', 'cer_service', 'agentshell_guard',
    }
    if name in SYSTEM_PROCESSES or name_no_ext in SYSTEM_PROCESSES:
        return 'system'

    # Network tools: proxies, VPNs
    NETWORK_PROCESSES = {
        # Windows
        'verge-mihomo.exe', 'clash-verge-service.exe', 'clash-verge.exe',
        'clash.exe', 'v2ray.exe', 'trojan.exe', 'ss-local.exe',
        # Unix/macOS
        'verge-mihomo', 'clash-verge-service', 'clash-verge',
        'clash', 'v2ray', 'trojan', 'ss-local', 'ss-server',
        'shadowsocks', 'trojan-go', 'xray',
    }
    if name in NETWORK_PROCESSES or name_no_ext in NETWORK_PROCESSES:
        return 'network'

    # Creative software
    CREATIVE_PROCESSES = {
        # Windows
        'houdini.exe', 'nuke15.0.exe', 'nuke.exe',
        'blender.exe', 'maya.exe', '3dsmax.exe', 'afterfx.exe',
        'photoshop.exe', 'illustrator.exe',
        # Unix/macOS
        'houdini', 'nuke15.0', 'nuke',
        'blender', 'maya', '3dsmax', 'afterfx',
        'photoshop', 'illustrator', 'gimp', 'inkscape',
        'davinci', 'fusion', 'cinema4d', 'c4d',
    }
    if name in CREATIVE_PROCESSES or name_no_ext in CREATIVE_PROCESSES:
        return 'creative'

    # License managers
    if name in {'rlm.exe', 'rlm', 'flexnet', 'flexlm'}:
        return 'system'

    # Default: user apps
    return 'user'


def group_ports_by_process(ports: List[dict]) -> List[dict]:
    """Group ports by PID, detect HTTP capability, return sorted list."""
    from collections import defaultdict

    groups = defaultdict(list)
    for port_info in ports:
        pid = port_info.get('pid')
        if pid:
            groups[pid].append(port_info)

    result = []
    for pid, port_list in groups.items():
        # Sort ports by port number
        port_list.sort(key=lambda p: p['port'])

        # Detect HTTP capability for each port (in parallel)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            http_futures = {
                executor.submit(check_http_port, p['port']): p
                for p in port_list
            }
            for future in concurrent.futures.as_completed(http_futures):
                port_info = http_futures[future]
                try:
                    port_info['is_http'] = future.result()
                except Exception:
                    port_info['is_http'] = False

        # Find primary port (first HTTP port, or lowest port number)
        http_ports = [p for p in port_list if p.get('is_http')]
        primary = http_ports[0] if http_ports else port_list[0]

        # Categorize process
        category = categorize_process(primary.get('process', 'Unknown'), [p['port'] for p in port_list])

        result.append({
            'pid': pid,
            'process_name': primary.get('process', 'Unknown'),
            'cwd': primary.get('project_name', ''),
            'ports': [p['port'] for p in port_list],
            'primary_port': primary['port'],
            'is_http': primary.get('is_http', False),
            'category': category,
            'port_count': len(port_list)
        })

    # Sort by: HTTP capability (yes first), then by primary port number
    result.sort(key=lambda g: (not g['is_http'], g['primary_port']))
    return result


def is_system_port(port: int) -> bool:
    """Check if a port is a known system/service port."""
    SYSTEM_PORTS = {
        7, 9, 13, 17, 19, 37, 53, 102, 111, 113, 119, 135, 137, 138, 139,
        161, 162, 389, 445, 464, 500, 514, 515, 593, 636, 902, 912, 993,
        995, 1714, 1715, 1745, 1900, 1928, 1929, 2049, 2100, 2869, 3306,
        3389, 3702, 5355, 5357, 5432, 5666, 6379, 7680, 11434, 27017
    }
    return port in SYSTEM_PORTS


def get_dashboard_snapshot(force_refresh: bool = False) -> dict:
    with concurrent.futures.ThreadPoolExecutor() as pool:
        ports_future = pool.submit(get_active_system_ports, force_refresh)
        stats_future = pool.submit(get_system_stats_snapshot, force_refresh)
        ports = ports_future.result()
        stats = stats_future.result()

    # Group ports by process and detect HTTP capability
    local_ports = [p for p in ports if p['port'] < 49152 and not is_system_port(p['port'])]
    grouped_local_ports = group_ports_by_process(local_ports)

    return {
        "stats": stats,
        "system_ports": ports,
        "grouped_local_ports": grouped_local_ports,
        "projects": get_projects_snapshot(active_ports=ports),
        "generated_at": int(time.time() * 1000),
    }


def parse_command(command: str) -> Tuple[List[str], dict]:
    stripped = command.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    try:
        parts = shlex.split(stripped, posix=not IS_WINDOWS)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid command syntax: {e}")

    env_overrides = {}
    while parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", parts[0]):
        key, value = parts.pop(0).split("=", 1)
        env_overrides[key] = value

    if not parts:
        raise HTTPException(status_code=400, detail="Command must include an executable after env assignments")
    return parts, env_overrides


def terminate_managed_pid(pid: int) -> bool:
    if pid <= 4:
        return False

    try:
        proc = psutil.Process(pid)
        proc_name = proc.name().lower()

        if IS_WINDOWS:
            PROTECTED_PROCESSES = {
                "svchost.exe", "csrss.exe", "smss.exe", "wininit.exe",
                "winlogon.exe", "lsass.exe", "services.exe", "system",
                "idle", "memory compression", "registry"
            }
        else:
            PROTECTED_PROCESSES = {
                "init", "systemd", "launchd", "kernel_task",
                "kthreadd", "ksoftirqd", "migration", "kworker"
            }

        if proc_name in PROTECTED_PROCESSES:
            print(f"Refused to kill protected system process: {proc_name} (PID {pid})")
            return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=5.0
            )
            return result.returncode == 0
        else:
            # Unix: kill entire process group
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                # If process group kill fails, try killing the process directly
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    child.kill()
                proc.kill()
            return True
    except Exception:
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


def append_log_line(project_id: str, text: str):
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def get_missing_log_message(project_id: str) -> dict:
    project = next((p for p in load_projects() if p["id"] == project_id), None)
    if not project:
        return {"logs": f"No log file found for project {project_id} yet.", "next_offset": 0, "truncated": False, "synthetic": True}

    project_state = next((p for p in get_projects_snapshot() if p["id"] == project_id), None)
    if project_state and project_state["status"] == "external":
        process = project_state.get("port_process") or {}
        logs = (
            f"=== PORT DASHBOARD ===\n"
            f"Project \"{project['name']}\" (port {project['port']}) is running externally.\n"
            f"PID: {process.get('pid')} (process: '{process.get('process', 'Unknown')}')\n\n"
            f"This process was not started by the dashboard, so logs are not captured.\n\n"
            f"To capture logs, stop the external process and restart via the dashboard."
        )
        return {"logs": logs, "next_offset": 0, "truncated": False, "synthetic": True}

    logs = (
        f"=== PORT DASHBOARD ===\n"
        f"Project \"{project['name']}\" (port {project['port']}) is stopped.\n\n"
        f"No logs yet. Click Start to begin capturing output."
    )
    return {"logs": logs, "next_offset": 0, "truncated": False, "synthetic": True}


@app.get("/api/system/stats")
def get_system_stats():
    return get_system_stats_snapshot()


@app.get("/api/system/ports")
def get_system_ports():
    return get_active_system_ports()


@app.get("/api/dashboard/snapshot")
def get_dashboard_snapshot_api(force: bool = False):
    return get_dashboard_snapshot(force_refresh=force)


@app.post("/api/system/ports/kill/{pid}")
def kill_system_process(pid: int):
    if pid <= 4:
        raise HTTPException(status_code=400, detail="Cannot kill system process")

    if terminate_managed_pid(pid):
        invalidate_ports_cache()
        return {"success": True, "message": f"Killed process PID {pid}"}
    raise HTTPException(status_code=500, detail=f"Failed to kill process {pid}")


@app.get("/api/projects")
def get_projects_api():
    return get_projects_snapshot()


@app.post("/api/projects")
def create_project(project: Project):
    projects = load_projects()
    if any(p["id"] == project.id for p in projects):
        raise HTTPException(status_code=400, detail="Project ID already exists")
    projects.append(apply_project_display_name(project.model_dump()))
    save_projects(projects)
    return {"success": True, "project": project}


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, updated_project: Project):
    project_id = validate_project_id(project_id)
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
    projects[index] = apply_project_display_name(updated_project.model_dump())
    save_projects(projects)
    return {"success": True, "project": updated_project}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    project_id = validate_project_id(project_id)
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        stop_project(project_id)
    except Exception:
        pass
    projects.pop(index)
    save_projects(projects)
    return {"success": True}


@app.post("/api/projects/{project_id}/start")
def start_project(project_id: str):
    project_id = validate_project_id(project_id)
    projects = load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    current_state = next((p for p in get_projects_snapshot() if p["id"] == project_id), None)
    if current_state and current_state["status"] == "running" and current_state["managed"]:
        raise HTTPException(status_code=400, detail=f"Project '{project['name']}' is already running under dashboard management")
    if current_state and current_state["status"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"Port {project['port']} is already occupied by external process '{current_state['port_process']['process']}' (PID {current_state['port_process']['pid']}). Please stop it first.",
        )

    cwd = project["cwd"]
    if not os.path.isdir(cwd):
        raise HTTPException(status_code=400, detail=f"Working directory does not exist: {cwd}")

    argv, env_overrides = parse_command(project["command"])
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        log_file.write(f"=== Starting project '{project['name']}' at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log_file.write(f"CWD: {cwd}\n")
        log_file.write(f"Command: {' '.join(argv)}\n")
        if env_overrides:
            log_file.write(f"Env Overrides: {json.dumps(env_overrides, ensure_ascii=False)}\n")
        log_file.write("===========================================================\n\n")
        log_file.flush()

        sub_env = os.environ.copy()
        sub_env.update(env_overrides)
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["FORCE_COLOR"] = "1"

        # Platform-specific process creation
        if IS_WINDOWS:
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=sub_env,
                creationflags=creation_flags,
            )
        else:
            # Unix: use start_new_session to create new process group
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=sub_env,
                start_new_session=True,
            )

        ACTIVE_PROCESSES[project_id] = proc
        ACTIVE_LOG_FILES[project_id] = log_file
        pids_map = load_running_pids()
        pids_map[project_id] = {
            "pid": proc.pid,
            "managed": True,
            "started_at": int(time.time()),
        }
        save_running_pids(pids_map)
        invalidate_ports_cache()
        return {"success": True, "pid": proc.pid, "message": f"Project '{project['name']}' started successfully"}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Executable not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start project: {str(e)}")


@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str):
    project_id = validate_project_id(project_id)
    projects = load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    current_state = next((p for p in get_projects_snapshot() if p["id"] == project_id), None)
    if current_state and current_state["status"] == "external":
        return {
            "success": False,
            "message": f"Project '{project['name']}' is currently running as an external process on port {project['port']}. Dashboard will not kill external processes automatically.",
            "external": True,
        }

    pids_map = load_running_pids()
    entry = pids_map.get(project_id)
    pid = None
    if project_id in ACTIVE_PROCESSES:
        pid = ACTIVE_PROCESSES[project_id].pid
        ACTIVE_PROCESSES.pop(project_id, None)
    elif entry:
        pid = entry["pid"]

    if not pid:
        return {"success": True, "message": "Project is not running (no managed process to stop)"}

    log_file = ACTIVE_LOG_FILES.pop(project_id, None)
    if log_file:
        try:
            log_file.close()
        except Exception:
            pass

    success = terminate_managed_pid(pid)
    pids_map.pop(project_id, None)
    save_running_pids(pids_map)
    invalidate_ports_cache()
    append_log_line(project_id, f"\n\n=== Project stopped at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    if success:
        return {"success": True, "message": f"Stopped managed project PID {pid}"}
    return {"success": False, "message": f"Could not stop managed process {pid} (it may have already exited)"}


@app.get("/api/projects/{project_id}/logs")
def get_project_logs(project_id: str, offset: int = 0, limit: int = LOG_READ_CHUNK_SIZE):
    project_id = validate_project_id(project_id)
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    if not os.path.exists(log_path):
        return get_missing_log_message(project_id)

    try:
        file_size = os.path.getsize(log_path)
        safe_limit = max(1024, min(limit, LOG_READ_CHUNK_SIZE))
        safe_offset = max(offset, 0)
        truncated = False
        if safe_offset > file_size:
            safe_offset = 0
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            if safe_offset == 0 and file_size > safe_limit:
                f.seek(file_size - safe_limit)
                truncated = True
            else:
                f.seek(safe_offset)
            logs = f.read(safe_limit)
            next_offset = f.tell()
        return {
            "logs": logs,
            "next_offset": next_offset,
            "truncated": truncated,
            "synthetic": False,
            "file_size": file_size,
        }
    except Exception as e:
        return {
            "logs": f"Error reading log file: {str(e)}",
            "next_offset": 0,
            "truncated": False,
            "synthetic": True,
        }


@app.post("/api/projects/{project_id}/logs/clear")
def clear_project_logs(project_id: str):
    project_id = validate_project_id(project_id)
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Logs cleared at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear logs: {str(e)}")
    return {"success": True}


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Dashboard UI (index.html) not found")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading dashboard file: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    reload_enabled = os.environ.get("PORT_DASHBOARD_RELOAD", "0") == "1"
    uvicorn.run("app:app", host="0.0.0.0", port=9229, reload=reload_enabled)
