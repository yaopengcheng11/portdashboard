import concurrent.futures
import asyncio
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
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil
from fastapi import FastAPI, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from port_parser import build_pid_name_map, parse_listening_ports as _parse_listening_ports_impl
from http_probe import check_http_port as _check_http_port_impl

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
PREFERENCES_FILE = os.path.join(BASE_DIR, "mydashboard-config.json")
DEFAULT_PORT = 9229
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
    startup_timeout_sec: int = 30
    health_check_url: str = ""


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
    """Fallback port scanner using netstat when psutil lacks permissions.

    Thin dispatcher — real per-platform logic lives in port_parser.py.
    Kept as a stable name so the cache layer (get_active_system_ports)
    and any external callers don't have to change.
    """
    try:
        pid_to_name = build_pid_name_map()
        return _parse_listening_ports_impl(pid_to_name)
    except Exception as e:
        print(f"Error parsing ports (netstat fallback): {e}")
        return []


def _enrich_with_dashboard_project(ports: List[dict]) -> List[dict]:
    """Add ``dashboard_project`` field to each port dict, mapping PID -> project_id.

    Lookup priority:
      1. ACTIVE_PROCESSES (in-memory, has the Popen objects) - authoritative
      2. running_pids.json (persisted registry, may have stale entries if process died)
    """
    # Build PID -> project_id map from ACTIVE_PROCESSES
    pid_to_project = {}
    for project_id, proc in ACTIVE_PROCESSES.items():
        try:
            if proc.pid:
                pid_to_project[proc.pid] = project_id
        except Exception:
            pass
    # Also check running_pids.json for managed-but-not-currently-tracked entries
    try:
        pids_map = load_running_pids()
        for project_id, entry in pids_map.items():
            pid = entry.get("pid") if isinstance(entry, dict) else None
            if pid and pid not in pid_to_project:
                pid_to_project[pid] = project_id
    except Exception:
        pass
    # Apply to each port
    for port_info in ports:
        pid = port_info.get("pid")
        port_info["dashboard_project"] = pid_to_project.get(pid) if pid else None
    return ports


def get_active_system_ports(force_refresh: bool = False) -> List[dict]:
    now = time.time()
    with PORTS_CACHE_LOCK:
        if not force_refresh and now - PORTS_CACHE["timestamp"] < PORTS_CACHE_TTL:
            return list(PORTS_CACHE["value"])

    ports_info = parse_listening_ports()
    _enrich_with_dashboard_project(ports_info)
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
    """Check if a port serves actual web content (not just HTTP protocol).

    Thin wrapper — actual probe logic lives in http_probe.py.
    """
    return _check_http_port_impl(port, timeout)


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


def _wait_for_startup(proc: subprocess.Popen, timeout_sec: int, health_url: str) -> Tuple[bool, str]:
    """
    Wait up to `timeout_sec` for `proc` to come up.

    If `health_url` is non-empty, polls it via urllib until a 2xx is seen or timeout.
    Otherwise falls back to checking that the process is still alive (poll() is None)
    and that the listening port (proc.pid port-inferred via the kernel is not reliable
    across platforms) is open — for the no-health-check case we just confirm the
    process didn't exit immediately.

    Returns (ok, error_message). On success error_message is empty.
    """
    import urllib.request as _ur
    import urllib.error as _ue

    deadline = time.time() + max(1, int(timeout_sec))
    poll_interval = 0.5

    while time.time() < deadline:
        # Did the child exit on its own? If so, startup failed.
        if proc.poll() is not None:
            return False, f"process exited with code {proc.returncode} before becoming ready"

        if health_url:
            try:
                with _ur.urlopen(health_url, timeout=2) as resp:
                    if 200 <= resp.status < 300:
                        return True, ""
            except (_ue.URLError, _ue.HTTPError, ConnectionError, OSError, TimeoutError):
                # Still warming up — keep polling until deadline.
                pass
        else:
            # No health URL: as soon as the process is still alive past the first
            # tick, treat it as started (matches previous "fire-and-forget" behavior).
            return True, ""

        time.sleep(poll_interval)

    # Timed out.
    if health_url:
        return False, f"health check {health_url!r} did not return 2xx within {timeout_sec}s"
    return False, f"process did not stay alive within {timeout_sec}s"


def _kill_active_proc(project_id: str, proc: subprocess.Popen) -> None:
    """Best-effort kill of `proc` (and its children) plus state cleanup."""
    try:
        if proc.poll() is None:
            try:
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    finally:
        ACTIVE_PROCESSES.pop(project_id, None)
        log_f = ACTIVE_LOG_FILES.pop(project_id, None)
        if log_f is not None:
            try:
                log_f.close()
            except Exception:
                pass


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

    # Pre-flight: 检查目标端口是否已被外部进程占用（强制刷新端口快照，避免竞态）
    active_ports = get_active_system_ports(force_refresh=True)
    port_conflict = next(
        (p for p in active_ports if p.get("port") == project["port"]),
        None,
    )
    if port_conflict:
        pid = port_conflict.get("pid")
        # 如果占用方就是本面板管理的进程（即已在 ACTIVE_PROCESSES），允许
        is_managed = any(proc.pid == pid for proc in ACTIVE_PROCESSES.values() if pid)
        if not is_managed:
            proc_name = port_conflict.get("process", "Unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Port {project['port']} is already in use by external process "
                    f"'{proc_name}' (PID {pid}). Stop it first or change the project's port.",
            )

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

        # Resolve startup timeout (clamp to 1..300s) and optional health URL.
        raw_timeout = project.get("startup_timeout_sec", 30)
        try:
            timeout_sec = int(raw_timeout)
        except (TypeError, ValueError):
            timeout_sec = 30
        timeout_sec = max(1, min(timeout_sec, 300))
        health_url = (project.get("health_check_url") or "").strip()

        ok, err = _wait_for_startup(proc, timeout_sec, health_url)
        if not ok:
            _kill_active_proc(project_id, proc)
            try:
                log_file.write("\n[startup check FAILED] " + err + "\n")
            except Exception:
                pass
            try:
                log_file.close()
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"Project '{project['name']}' failed to become ready within {timeout_sec}s: {err}",
            )

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


@app.get("/api/projects/{project_id}/logs/stream")
async def stream_logs(project_id: str):
    """SSE stream of new log lines as they appear. Starts from current end-of-file (no replay)."""
    project_id = validate_project_id(project_id)
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    return StreamingResponse(
        _sse_event_generator(log_path, project_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse_event_generator(log_path: str, project_id: str):
    """Tail-follow a log file, yielding SSE-formatted lines for each new chunk."""
    last_pos = _initial_log_position(log_path)
    if last_pos is None:
        yield f"data: [synthetic] log file not found for {project_id}\n\n"
        return

    while True:
        chunk = await _read_new_chunk(log_path, last_pos)
        if chunk is None:
            await asyncio.sleep(0.5)
            continue
        new_data, current_pos = chunk
        if new_data:
            last_pos = current_pos
            for line in _iter_lines(new_data):
                yield f"data: {line}\n\n"
        await asyncio.sleep(0.5)


def _initial_log_position(log_path: str):
    """Return byte offset of EOF, or None if the file is missing (truncated = 0)."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            return f.tell()
    except FileNotFoundError:
        return None


async def _read_new_chunk(log_path: str, last_pos: int):
    """Read bytes appended to log_path since last_pos. Returns (data, new_pos) or None."""
    try:
        with open(log_path, "rb") as f:
            f.seek(last_pos)
            data = f.read()
            return data, f.tell()
    except (FileNotFoundError, OSError):
        return None


def _iter_lines(data: bytes):
    """Decode bytes and yield each line as a single-line SSE-safe string."""
    text = data.decode("utf-8", errors="ignore")
    for line in text.splitlines():
        # Strip CR and escape any embedded newlines so each yield is a single line.
        yield line.replace(chr(13), "").replace("\n", "\\n")


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


@app.get("/")
def serve_dashboard():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Dashboard UI (index.html) not found")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            body = f.read()
        headers = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
        return HTMLResponse(content=body, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading dashboard file: {str(e)}")


# ---------------------------------------------------------------------------
# User preferences (settings panel)
# Stored server-side in mydashboard-config.json so values like 'port' survive
# across sessions and restart. Theme/auto-refresh/refresh-interval are also
# read here at boot so the UI hydrates from server defaults before paint.
# ---------------------------------------------------------------------------

ALLOWED_THEMES = {"dark-emerald", "blueprint", "midnight", "arctic", "terra", "neon", "velvet"}
ALLOWED_CATEGORIES = {"all", "user", "creative"}
ALLOWED_REFRESH_INTERVALS = (3, 5, 10, 15, 30, 60)

DEFAULT_PREFERENCES = {
    "theme": "dark-emerald",
    "default_category": "user",
    "auto_refresh": True,
    "refresh_interval": 5,         # seconds
    "port": DEFAULT_PORT,          # binding port; takes effect after restart
}

# Set by __main__ right before uvicorn.run() binds the socket.
# Before then, falls back to DEFAULT_PORT so import-time reads are safe.
RUNNING_PORT: int = DEFAULT_PORT


def _coerce_preferences(raw: dict) -> dict:
    """Merge user-provided values onto DEFAULT_PREFERENCES, dropping garbage."""
    out = dict(DEFAULT_PREFERENCES)
    if not isinstance(raw, dict):
        return out
    if raw.get("theme") in ALLOWED_THEMES:
        out["theme"] = raw["theme"]
    if raw.get("default_category") in ALLOWED_CATEGORIES:
        out["default_category"] = raw["default_category"]
    if isinstance(raw.get("auto_refresh"), bool):
        out["auto_refresh"] = raw["auto_refresh"]
    try:
        iv = int(raw.get("refresh_interval"))
        if iv in ALLOWED_REFRESH_INTERVALS:
            out["refresh_interval"] = iv
    except (TypeError, ValueError):
        pass
    try:
        p = int(raw.get("port"))
        if 1 <= p <= 65535 and p != DEFAULT_PORT:
            # Non-default ports are stored; default value is implicit.
            out["port"] = p
        elif p == DEFAULT_PORT:
            out["port"] = DEFAULT_PORT
    except (TypeError, ValueError):
        pass
    return out


def load_preferences() -> dict:
    """Read preferences from disk, falling back to defaults on any error."""
    if not os.path.exists(PREFERENCES_FILE):
        return dict(DEFAULT_PREFERENCES)
    try:
        with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return _coerce_preferences(raw)
    except Exception:
        return dict(DEFAULT_PREFERENCES)


def save_preferences(prefs: dict) -> dict:
    """Persist coerced preferences; uses atomic_write_json for crash safety."""
    coerced = _coerce_preferences(prefs)
    atomic_write_json(PREFERENCES_FILE, coerced)
    return coerced


@app.get("/api/preferences")
def get_preferences():
    """Return current preferences + the actually-running port.

    `running_port` is set by __main__ right before uvicorn.run(); before that
    (e.g. during tests or import) it falls back to DEFAULT_PORT.
    """
    prefs = load_preferences()
    return {
        "preferences": prefs,
        "running_port": RUNNING_PORT,
        "defaults": DEFAULT_PREFERENCES,
        "allowed": {
            "themes": sorted(ALLOWED_THEMES),
            "categories": sorted(ALLOWED_CATEGORIES),
            "refresh_intervals": list(ALLOWED_REFRESH_INTERVALS),
        },
    }


@app.put("/api/preferences")
def update_preferences(prefs: dict):
    """Update one or more preference fields. Port change requires restart."""
    if not isinstance(prefs, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    current = load_preferences()
    merged = {**current, **prefs}
    saved = save_preferences(merged)
    port_changed = "port" in prefs and prefs.get("port") != current.get("port")
    return {
        "success": True,
        "preferences": saved,
        "requires_restart": port_changed,
        "message": "Restart required for port change to take effect." if port_changed else None,
    }





if __name__ == "__main__":
    import uvicorn

    # Prefer env var > preferences file > 9229 default.
    # NOTE: changing this requires a server restart — the port is bound once.
    def _resolve_bind_port() -> int:
        env_port = os.environ.get("MYDASHBOARD_PORT")
        if env_port and env_port.isdigit():
            return int(env_port)
        try:
            prefs = load_preferences()
            file_port = prefs.get("port")
            if isinstance(file_port, int) and 1 <= file_port <= 65535:
                return file_port
        except Exception:
            pass
        return DEFAULT_PORT

    reload_enabled = os.environ.get("PORT_DASHBOARD_RELOAD", "0") == "1"
    bind_port = _resolve_bind_port()
    print(f"[mydashboard] binding to 0.0.0.0:{bind_port} (set MYDASHBOARD_PORT=... to override)")
    uvicorn.run("app:app", host="0.0.0.0", port=bind_port, reload=reload_enabled)
