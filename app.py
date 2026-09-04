import concurrent.futures
import asyncio
import io
import json
import os
import platform
import re
import shlex
import shutil
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
from port_parser import (
    build_pid_name_map,
    parse_listening_ports as _parse_listening_ports_impl,
    format_addr,
)
from http_probe import check_http_port as _check_http_port_impl
from discovery import discover_projects as _discover_projects, slugify_project_id, \
    detect_project_groups as _detect_project_groups

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

@asynccontextmanager
async def lifespan(app: FastAPI):
    readopt_processes()
    ensure_background_refresh_thread()
    ensure_background_watchdog_thread()
    invalidate_ports_cache()
    yield

app = FastAPI(title="MyDashboard - Port Control Center", lifespan=lifespan)


class LocalCORSMiddleware(BaseHTTPMiddleware):
    """仅放行面板自身来源的 CORS 请求（前端与 API 同源，正常情况下不需要跨域）"""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        allowed_origins = {
            f"http://localhost:{RUNNING_PORT}",
            f"http://127.0.0.1:{RUNNING_PORT}",
            f"http://localhost:{DEFAULT_PORT}",
            f"http://127.0.0.1:{DEFAULT_PORT}",
        }

        response = await call_next(request)
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            if request.method == "OPTIONS":
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response


app.add_middleware(LocalCORSMiddleware)

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
PROC_LOCK = threading.RLock()
START_TIME = time.time()
PORTS_CACHE = {"timestamp": 0.0, "value": []}
STATS_CACHE = {"timestamp": 0.0, "value": {}}
PROJECTS_LOCK = threading.Lock()
PIDS_LOCK = threading.Lock()
PORTS_CACHE_LOCK = threading.Lock()
STATS_CACHE_LOCK = threading.Lock()
PORTS_REFRESH_THREAD_STARTED = False

HTTP_PROBE_CACHE: Dict[int, Tuple[float, bool]] = {}
HTTP_PROBE_CACHE_TTL = 30.0
HTTP_PROBE_CACHE_LOCK = threading.Lock()
HTTP_PROBE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="http-probe")

PROJECT_NAME_CACHE: Dict[int, Tuple[float, str]] = {}
PROJECT_NAME_CACHE_TTL = 60.0
PROJECT_NAME_CACHE_LOCK = threading.Lock()


class Project(BaseModel):
    id: str
    name: str
    cwd: str
    command: str
    port: int
    description: Optional[str] = ""
    sync_name: bool = False
    auto_restart: bool = False
    startup_timeout_sec: int = 30
    health_check_url: str = ""


# id 会被用作日志文件名（{id}.log），因此按"安全文件名"标准收紧：
# 字母/数字开头，只含字母数字 - _ ；显式挡掉 Windows 保留设备名（con.log 这类
# 即使带扩展名也会被 NTFS 当设备解析）。
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def validate_project_id(project_id: str) -> str:
    if (
        not project_id
        or not _PROJECT_ID_RE.match(project_id)
        or project_id.lower() in _WINDOWS_RESERVED_NAMES
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid project ID: use 1-64 chars of letters, digits, '-' or '_', starting with a letter or digit",
        )
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
                data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        # 损坏时改名隔离而不是静默吞掉：否则下一次 save_projects 会把
        # 仅存的原始数据覆盖成空表 + 新条目，用户项目全丢。
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            with PROJECTS_LOCK:
                os.replace(PROJECTS_FILE, f"{PROJECTS_FILE}.corrupt-{stamp}")
            print(f"projects.json 已损坏，已隔离为 projects.json.corrupt-{stamp}；返回空项目列表")
        except OSError:
            pass
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
    normalized["auto_restart"] = bool(normalized.get("auto_restart", False))
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


def _pid_matches_start(pid: int, started_at) -> bool:
    """PID 复用防护：进程的创建时间必须与注册时的 started_at 对得上。

    PID 在进程死后会被系统复用——只检查 pid_exists 会把一个无关新进程
    认领成托管项目，之后"停止"就会误杀它。started_at 为 None（旧格式
    注册表，无法比对）时放行，保持向后兼容。
    """
    if not started_at:
        return True
    try:
        create_time = psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    # started_at 在 spawn 之后取样，create_time 在 spawn 时刻，同源时钟，
    # 容差 2s 足够覆盖取值延迟；PID 复用的新进程 create_time 必然晚得多。
    return abs(create_time - started_at) <= 2.0


def _infer_project_name_for_pid(pid: int) -> str:
    now = time.time()
    with PROJECT_NAME_CACHE_LOCK:
        cached = PROJECT_NAME_CACHE.get(pid)
        if cached and now - cached[0] < PROJECT_NAME_CACHE_TTL:
            return cached[1]
    name = ""
    try:
        cwd = psutil.Process(pid).cwd()
        name = infer_project_display_name(cwd) or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    with PROJECT_NAME_CACHE_LOCK:
        PROJECT_NAME_CACHE[pid] = (now, name)
        if len(PROJECT_NAME_CACHE) > 512:
            for key, (ts, _) in list(PROJECT_NAME_CACHE.items()):
                if now - ts >= PROJECT_NAME_CACHE_TTL:
                    PROJECT_NAME_CACHE.pop(key, None)
    return name


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
                    proc_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                project_name = _infer_project_name_for_pid(pid)
            ports_info.append({
                "address": format_addr(conn.laddr.ip, port),
                "port": port,
                "process": proc_name,
                "pid": pid,
                "status": "listening",
                "platform": sys.platform,
                "project_name": project_name,
                "cwd": _process_cwd(pid),
            })
            seen_ports.add(port)
    except (psutil.AccessDenied, OSError) as e:
        # macOS 上系统级 net_connections 需要 root，这条回退是常态路径
        print(f"psutil.net_connections 无权限 ({e})，改用逐进程枚举")
        ports_info = _parse_ports_fallback()
    return ports_info


def _process_cwd(pid: Optional[int]) -> str:
    if not pid:
        return ""
    try:
        return psutil.Process(pid).cwd() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return ""


def _parse_ports_fallback() -> List[dict]:
    """psutil 系统级调用没权限时的回退端口扫描。

    薄分派层，各平台实现在 port_parser.py。
    pid→name 映射只有 Windows 的 netstat 解析需要；unix 路径逐进程枚举，
    进程名随连接一起拿到，不必白建一份 600+ 条的映射。

    项目名与 cwd 的推断在这里补上 —— port_parser 只负责平台差异，
    不该反过来 import app（会循环依赖）。
    """
    try:
        pid_to_name = build_pid_name_map() if IS_WINDOWS else {}
        ports = _parse_listening_ports_impl(pid_to_name)
    except Exception as e:
        print(f"Error parsing ports (fallback): {e}")
        return []

    for port_info in ports:
        pid = port_info.get("pid")
        port_info["project_name"] = _infer_project_name_for_pid(pid) if pid else ""
        port_info["cwd"] = _process_cwd(pid)
    return ports


def _collect_managed_pids() -> Dict[int, str]:
    """Map every PID belonging to a managed project -> project_id.

    包含托管进程的全部后代：Windows 上启动链常有中间层（WindowsApps 存根、
    npm.cmd -> cmd.exe -> node），真正监听端口的 PID 是 Popen 进程的子孙，
    只按直接 PID 匹配会让 dashboard_project 标记与启动预检全部落空。
    """
    root_to_project: Dict[int, str] = {}
    with PROC_LOCK:
        active_snapshot = dict(ACTIVE_PROCESSES)
    for project_id, proc in active_snapshot.items():
        try:
            if proc.pid:
                root_to_project[proc.pid] = project_id
        except Exception:
            pass
    # Also check running_pids.json for managed-but-not-currently-tracked entries
    try:
        pids_map = load_running_pids()
        for project_id, entry in pids_map.items():
            pid = entry.get("pid") if isinstance(entry, dict) else None
            if pid and pid not in root_to_project:
                root_to_project[pid] = project_id
    except Exception:
        pass

    pid_to_project: Dict[int, str] = {}
    for root_pid, project_id in root_to_project.items():
        pid_to_project[root_pid] = project_id
        try:
            for child in psutil.Process(root_pid).children(recursive=True):
                pid_to_project[child.pid] = project_id
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    return pid_to_project


def _project_cwd_map() -> dict:
    """归一化的项目 cwd -> 项目 id；同目录多个项目视为歧义，不参与归因。"""
    cwd_map: dict = {}
    for p in load_projects():
        cwd = p.get("cwd")
        if not cwd:
            continue
        key = os.path.normcase(os.path.normpath(cwd))
        if key in cwd_map:
            cwd_map[key] = None
        else:
            cwd_map[key] = p["id"]
    return {k: v for k, v in cwd_map.items() if v}


def _project_by_process_cwd(proc_cwd: str, cwd_map: dict) -> Optional[str]:
    """按进程工作目录归因项目：精确命中优先，其次"在某项目目录之下"（monorepo）。"""
    if not proc_cwd or not cwd_map:
        return None
    key = os.path.normcase(os.path.normpath(proc_cwd))
    hit = cwd_map.get(key)
    if hit:
        return hit
    for proj_cwd, project_id in cwd_map.items():
        if key.startswith(proj_cwd.rstrip("\\/") + os.sep):
            return project_id
    return None


def _enrich_with_dashboard_project(ports: List[dict]) -> List[dict]:
    """Add ``dashboard_project`` to each port dict, mapping PID -> project_id.

    归因优先级：
      1. 托管进程树（ACTIVE_PROCESSES + running_pids.json，含全部子孙）—— 权威
      2. **cwd 归因** —— 进程工作目录对上某个项目的 cwd（或其子目录）。
         解决"用户手动在终端里启动了项目"的边界：不是面板起的，但端口
         显然属于这个项目。此时仍标记为外部进程（面板不会去杀它），
         但归属清晰。
    """
    pid_to_project = _collect_managed_pids()
    cwd_map = _project_cwd_map()
    for port_info in ports:
        pid = port_info.get("pid")
        owner = pid_to_project.get(pid) if pid else None
        if owner:
            port_info["dashboard_project"] = owner
            port_info["attribution"] = "managed"
            continue
        owner = _project_by_process_cwd(port_info.get("cwd") or "", cwd_map)
        port_info["dashboard_project"] = owner
        port_info["attribution"] = "cwd" if owner else None
    return ports


def get_active_system_ports(force_refresh: bool = False) -> List[dict]:
    now = time.time()
    with PORTS_CACHE_LOCK:
        if not force_refresh and now - PORTS_CACHE["timestamp"] < PORTS_CACHE_TTL:
            return [dict(p) for p in PORTS_CACHE["value"]]

    ports_info = parse_listening_ports()
    _enrich_with_dashboard_project(ports_info)
    ports_info.sort(key=lambda x: x["port"])
    with PORTS_CACHE_LOCK:
        PORTS_CACHE["timestamp"] = time.time()
        PORTS_CACHE["value"] = ports_info
        return [dict(p) for p in ports_info]


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


# ---------------------------------------------------------------------------
# Crash watchdog — auto_restart 项目的意外退出拉起。
#
# 语义约定：
#   * 只重启"曾见它活着"的项目 —— 开机时不会把所有停止的项目拉起来；
#   * 手动 stop / delete 会把项目加入 WATCHDOG_SUPPRESS，直到下次手动 start；
#   * 连续存活超过 60s 视为稳定，退避计数清零；重启失败按 5/10/20/40/60s 退避；
#   * 端口仍被外部进程占住时不重启（多半是崩溃残留的孤儿进程），暂停并记日志。
# ---------------------------------------------------------------------------

WATCHDOG_SUPPRESS: set = set()
WATCHDOG_STATE: Dict[str, dict] = {}   # project_id -> {pid, up_since, failures, next_retry_at}
WATCHDOG_TICK = 5.0
WATCHDOG_BACKOFF = (5, 10, 20, 40, 60)
WATCHDOG_STABLE_AFTER = 60.0
WATCHDOG_THREAD_STARTED = False


def _watchdog_backoff(failures: int) -> float:
    return WATCHDOG_BACKOFF[min(max(failures, 0), len(WATCHDOG_BACKOFF) - 1)]


def _project_running_pid(project: dict) -> Optional[int]:
    """项目当前是否有活着的托管进程：ACTIVE 优先，其次注册表（含 PID 复用比对）。"""
    project_id = project["id"]
    with PROC_LOCK:
        proc = ACTIVE_PROCESSES.get(project_id)
        if proc and proc.poll() is None:
            return proc.pid
    entry = load_running_pids().get(project_id)
    if entry and is_pid_running(entry["pid"]) and _pid_matches_start(entry["pid"], entry.get("started_at")):
        return entry["pid"]
    return None


def _watchdog_restart(project: dict) -> Tuple[bool, str, Optional[int]]:
    """看护重启：端口预检 → 复用统一 spawn 路径 → 短暂确认存活。"""
    project_id = project["id"]
    try:
        active_ports = get_active_system_ports(force_refresh=True)
        conflict = next((p for p in active_ports if p.get("port") == project["port"]), None)
        if conflict and conflict.get("pid") not in _collect_managed_pids():
            return False, (
                f"port {project['port']} still held by external process "
                f"'{conflict.get('process')}' (PID {conflict.get('pid')}); restart paused"
            ), None
        if not os.path.isdir(project["cwd"]):
            return False, f"working directory missing: {project['cwd']}", None
        argv, env_overrides = parse_command(project["command"])
        argv = _resolve_executable(argv)
        proc = _spawn_and_register(project, argv, env_overrides, log_mode="a")
    except Exception as e:
        return False, f"spawn failed: {e}", None

    # 给 2 秒确认真的起来了（与无 health_url 的手动启动语义一致）
    time.sleep(2)
    if proc.poll() is not None:
        return False, f"process exited immediately with code {proc.returncode}", proc.pid
    pids_map = load_running_pids()
    pids_map[project_id] = {"pid": proc.pid, "managed": True, "started_at": time.time()}
    save_running_pids(pids_map)
    invalidate_ports_cache()
    return True, f"restarted as PID {proc.pid}", proc.pid


def _watchdog_tick():
    for project in load_projects():
        project_id = project["id"]
        if not project.get("auto_restart") or project_id in WATCHDOG_SUPPRESS:
            WATCHDOG_STATE.pop(project_id, None)
            continue

        state = WATCHDOG_STATE.setdefault(project_id, {"pid": None, "up_since": None,
                                                       "failures": 0, "next_retry_at": 0.0})
        now = time.time()
        pid = _project_running_pid(project)
        if pid:
            if state.get("pid") != pid:
                state["pid"] = pid
                state["up_since"] = now
            elif state.get("up_since") and now - state["up_since"] > WATCHDOG_STABLE_AFTER:
                state["failures"] = 0
            continue

        # 进程没了：只有这轮巡检之前见过它活着，才算"意外退出"。
        if not state.get("pid"):
            continue
        if now < state.get("next_retry_at", 0.0):
            continue

        failures = state.get("failures", 0)
        append_log_line(
            project_id,
            f"\n[watchdog] managed process (PID {state['pid']}) exited unexpectedly; "
            f"auto-restarting (attempt {failures + 1})\n",
        )
        ok, detail, new_pid = _watchdog_restart(project)
        if ok:
            state.update({"pid": new_pid, "up_since": time.time(),
                          "failures": failures + 1, "next_retry_at": 0.0})
            append_log_line(project_id, f"[watchdog] {detail}\n")
        else:
            delay = _watchdog_backoff(failures + 1)
            state.update({"failures": failures + 1, "next_retry_at": time.time() + delay,
                          "pid": None, "up_since": None})
            append_log_line(project_id, f"[watchdog] restart failed: {detail}; retry in {delay}s\n")


def background_watchdog():
    while True:
        try:
            _watchdog_tick()
        except Exception as e:
            print(f"Watchdog error: {e}")
        time.sleep(WATCHDOG_TICK)


def ensure_background_watchdog_thread():
    global WATCHDOG_THREAD_STARTED
    if WATCHDOG_THREAD_STARTED:
        return
    thread = threading.Thread(target=background_watchdog, daemon=True, name="crash-watchdog")
    thread.start()
    WATCHDOG_THREAD_STARTED = True


def cleanup_stale_process_tracking(project_id: str, pids_map: Optional[dict] = None) -> bool:
    """Drop dead entries; returns True if `pids_map` was modified.

    When called without `pids_map`, loads and saves the registry itself;
    otherwise the caller is responsible for persisting changes.
    """
    with PROC_LOCK:
        proc = ACTIVE_PROCESSES.get(project_id)
        if proc and proc.poll() is not None:
            ACTIVE_PROCESSES.pop(project_id, None)
    standalone = pids_map is None
    if standalone:
        pids_map = load_running_pids()
    dirty = False
    entry = pids_map.get(project_id)
    if entry and not is_pid_running(entry["pid"]):
        pids_map.pop(project_id, None)
        dirty = True
    if dirty and standalone:
        save_running_pids(pids_map)
    return dirty


def readopt_processes():
    pids_map = load_running_pids()
    updated_pids_map = {}
    for proj_id, entry in pids_map.items():
        pid = entry["pid"]
        if is_pid_running(pid) and _pid_matches_start(pid, entry.get("started_at")):
            updated_pids_map[proj_id] = entry
            print(f"Re-adopted running project {proj_id} with PID {pid}")
        else:
            print(f"Project {proj_id} with PID {pid} is no longer running (or PID was reused)")
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


def get_project_runtime_state(project: dict, active_ports: List[dict], pids_map: dict) -> Tuple[dict, bool]:
    project_id = project["id"]
    target_port = project["port"]
    dirty = cleanup_stale_process_tracking(project_id, pids_map)

    port_match = next((p for p in active_ports if p["port"] == target_port), None)
    status = "stopped"
    current_pid = None
    process_owner = "Unknown"
    managed = False
    external_self = False

    with PROC_LOCK:
        proc = ACTIVE_PROCESSES.get(project_id)
        if proc and proc.poll() is not None:
            ACTIVE_PROCESSES.pop(project_id, None)
            proc = None
    if proc:
        status = "running"
        current_pid = proc.pid
        process_owner = "Dashboard"
        managed = True
    else:
        entry = pids_map.get(project_id)
        if entry and is_pid_running(entry["pid"]) and _pid_matches_start(entry["pid"], entry.get("started_at")):
            status = "running"
            current_pid = entry["pid"]
            process_owner = "Dashboard (Adopted)"
            managed = True
        elif entry:
            # 进程已死，或 PID 已被复用（create_time 对不上）——都按失效处理
            pids_map.pop(project_id, None)
            dirty = True

    if status == "stopped" and port_match:
        status = "external"
        current_pid = port_match["pid"]
        process_owner = f"External ({port_match['process']})"
        # cwd 归因命中：不是面板起的，但监听进程的工作目录就是这个项目 ——
        # 让卡片如实显示"本项目（外部启动）"而不是泛泛的外部占用。
        external_self = port_match.get("attribution") == "cwd"
        if external_self:
            process_owner = f"External ({port_match['process']} · 本项目目录)"

    state = {
        **project,
        "status": status,
        "pid": current_pid,
        "owner": process_owner,
        "port_active": port_match is not None,
        "port_process": port_match,
        "managed": managed,
        "external_self": external_self,
    }
    return state, dirty


def get_projects_snapshot(active_ports: Optional[List[dict]] = None) -> List[dict]:
    projects = [apply_project_display_name(project) for project in load_projects()]
    if active_ports is None:
        active_ports = get_active_system_ports()
    pids_map = load_running_pids()
    states = []
    dirty = False
    for project in projects:
        state, changed = get_project_runtime_state(project, active_ports, pids_map)
        dirty = dirty or changed
        states.append(state)
    if dirty:
        save_running_pids(pids_map)
    return states


def check_http_port(port: int, timeout: float = 1.5) -> bool:
    """Check if a port serves actual web content (not just HTTP protocol).

    Thin wrapper — actual probe logic lives in http_probe.py.
    """
    return _check_http_port_impl(port, timeout)


def check_http_port_cached(port: int) -> bool:
    now = time.time()
    with HTTP_PROBE_CACHE_LOCK:
        cached = HTTP_PROBE_CACHE.get(port)
        if cached and now - cached[0] < HTTP_PROBE_CACHE_TTL:
            return cached[1]
    result = check_http_port(port)
    with HTTP_PROBE_CACHE_LOCK:
        HTTP_PROBE_CACHE[port] = (time.time(), result)
    return result


PROTECTED_PROCESSES_WINDOWS = {
    "svchost.exe", "csrss.exe", "smss.exe", "wininit.exe",
    "winlogon.exe", "lsass.exe", "services.exe", "system",
    "idle", "memory compression", "registry",
}
PROTECTED_PROCESSES_UNIX = {
    "init", "systemd", "launchd", "kernel_task",
    "kthreadd", "ksoftirqd", "migration", "kworker",
    # macOS 核心守护（误杀即系统级故障）
    "windowserver", "securityd", "mdnsresponder", "opendirectoryd",
    "syslogd", "cfprefsd", "cfprefsdd", "diskarbitrationd", "powerd", "hidd",
    # Linux 核心守护（sshd 被杀会锁死远程会话）
    "dbus-daemon", "dbusd", "polkitd", "networkmanager", "systemd-resolved",
    "udevd", "sshd", "snapd", "rsyslogd", "cron", "crond", "atd",
}


def _kill_process_tree(pid: int) -> bool:
    """Kill a process and all its children directly via psutil. Best-effort."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True  # 目标已经不在了，视为成功
    except psutil.AccessDenied:
        return False
    try:
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        proc.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def categorize_process(process_name: str) -> str:
    """Categorize a process into user-facing groups."""
    name = process_name.lower()
    # Strip .exe suffix for cross-platform compatibility
    name_no_ext = name.replace('.exe', '') if name.endswith('.exe') else name

    # System/vendor services: should not be stopped
    SYSTEM_PROCESSES = PROTECTED_PROCESSES_WINDOWS | PROTECTED_PROCESSES_UNIX | {
        # Windows vendor services
        'vpnagent.exe', 'cer_service.exe', 'agentshell_guard.exe',
        'asus_framework.exe', 'rogiveservice.exe', 'armourycrate.service.exe',
        'rogliveservice.exe', 'alilangclient.exe',
        # Unix/macOS
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

    # Probe all ports once via the shared pool (results cached with TTL)
    all_port_infos = [p for port_list in groups.values() for p in port_list]
    http_futures = {
        HTTP_PROBE_POOL.submit(check_http_port_cached, p['port']): p
        for p in all_port_infos
    }
    for future in concurrent.futures.as_completed(http_futures):
        port_info = http_futures[future]
        try:
            port_info['is_http'] = future.result()
        except Exception:
            port_info['is_http'] = False

    result = []
    for pid, port_list in groups.items():
        port_list.sort(key=lambda p: p['port'])

        # Find primary port (first HTTP port, or lowest port number)
        http_ports = [p for p in port_list if p.get('is_http')]
        primary = http_ports[0] if http_ports else port_list[0]

        # Categorize process
        category = categorize_process(primary.get('process', 'Unknown'))

        result.append({
            'pid': pid,
            'process_name': primary.get('process', 'Unknown'),
            'project_name': primary.get('project_name', ''),
            'cwd': primary.get('cwd', ''),
            'dashboard_project': primary.get('dashboard_project'),
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


def _resolve_executable(argv: List[str]) -> List[str]:
    """把裸命令名解析成 PATH 里的真实可执行路径。

    Windows 的 CreateProcess 不会按 PATHEXT 解析 .cmd/.bat shim —— list 形式的
    Popen(["npm", ...]) 直接 FileNotFoundError [WinError 2]，而 npm/npx/pnpm/vite
    在 Windows 上全是 .cmd shim。shutil.which 会查 PATHEXT，能把 npm 解析成
    npm.cmd 的全路径（.bat/.cmd 由 CreateProcess 自动经 cmd.exe 执行）。
    Unix 上 which 只是把 PATH 解析显式化，无副作用。
    """
    if not argv:
        return argv
    exe = argv[0]
    if os.path.dirname(exe):
        return argv  # 已带路径，尊重用户写法
    resolved = shutil.which(exe)
    if not resolved and not IS_WINDOWS and exe in ("python", "python.exe"):
        # 现代 macOS（12.3+ 移除了 /usr/bin/python）与多数 Linux 发行版
        # 只有 python3 —— 用户从 Windows 拷来的配置里写着 python 时，
        # 静默回退到 python3，而不是启动失败。
        resolved = shutil.which("python3")
    if resolved:
        return [resolved] + argv[1:]
    return argv  # 保持原样，让 Popen 抛出可读的 FileNotFoundError


def _spawn_and_register(project: dict, argv: List[str], env_overrides: dict,
                        log_mode: str = "w") -> subprocess.Popen:
    """打开项目日志、启动进程、登记为 active。

    手动启动与崩溃看护共用这一条路径；watchdog 重启传 log_mode="a"
    （追加，保留崩溃现场），手动启动默认 "w"（截断开新头）。
    """
    project_id = project["id"]
    cwd = project["cwd"]
    log_file = open(os.path.join(LOGS_DIR, f"{project_id}.log"), log_mode, encoding="utf-8")
    if log_mode == "w":
        log_file.write(f"=== Starting project '{project['name']}' at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    else:
        log_file.write(f"=== Watchdog restarting project '{project['name']}' at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
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

    with PROC_LOCK:
        ACTIVE_PROCESSES[project_id] = proc
        ACTIVE_LOG_FILES[project_id] = log_file
    return proc


def terminate_managed_pid(pid: int) -> bool:
    if pid <= 4:
        return False

    try:
        proc_name = psutil.Process(pid).name().lower()
        protected = PROTECTED_PROCESSES_WINDOWS if IS_WINDOWS else PROTECTED_PROCESSES_UNIX
        if proc_name in protected:
            print(f"Refused to kill protected system process: {proc_name} (PID {pid})")
            return False
    except psutil.NoSuchProcess:
        return True  # 已经退出
    except (psutil.AccessDenied, OSError):
        pass

    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True,
                encoding="mbcs", errors="ignore",  # 中文 Windows 的 taskkill 输出是 GBK
                timeout=5.0,
            )
            return result.returncode == 0
        else:
            # Unix: 先对整个进程组发 SIGTERM，给它善终的机会
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                # 组杀失败（如非组头/无权限），退化为直接杀进程树
                return _kill_process_tree(pid)
            # 等它退出；超时升级 SIGKILL。必须核实结果再返回，
            # 否则 stop 会虚报成功而进程其实还活着。
            try:
                psutil.Process(pid).wait(timeout=3)
                return True
            except psutil.TimeoutExpired:
                print(f"PID {pid} did not exit after SIGTERM, escalating to SIGKILL")
                return _kill_process_tree(pid)
            except psutil.NoSuchProcess:
                return True
    except Exception:
        return _kill_process_tree(pid)


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
    validate_project_id(project.id)
    projects = load_projects()
    if any(p["id"] == project.id for p in projects):
        raise HTTPException(status_code=400, detail="Project ID already exists")
    projects.append(apply_project_display_name(project.model_dump()))
    save_projects(projects)
    return {"success": True, "project": project}


@app.get("/api/discover")
def discover_projects_api(root: str, max_depth: int = 2):
    """扫描 root 目录，返回可托管项目候选（前端勾选后走 POST /api/projects 导入）。"""
    root_path = root.strip()
    if not root_path or not os.path.isdir(root_path):
        raise HTTPException(status_code=400, detail=f"Root directory does not exist: {root_path}")
    candidates = _discover_projects(root_path, max_depth=max(1, min(max_depth, 4)))
    managed_cwds = {
        os.path.normcase(os.path.normpath(p.get("cwd", "")))
        for p in load_projects()
    }
    for candidate in candidates:
        candidate["already_managed"] = \
            os.path.normcase(os.path.normpath(candidate["cwd"])) in managed_cwds
    # 配套组合建议：前端配置里的端口引用 + 命名配套（steps 为 id_hint；
    # name 一并喂 id_hint —— 显示名可能是中文，剥不出角色后缀）
    groups = _detect_project_groups([
        {"id": c["id_hint"], "name": c["id_hint"], "cwd": c["cwd"], "port": c["port"]}
        for c in candidates
    ])
    return {"root": root_path, "candidates": candidates, "groups": groups}


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, updated_project: Project):
    project_id = validate_project_id(project_id)
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
    # 身份以 URL 路径为准：body 里的 id 与路径不一致时会被整体写回，
    # 导致 ACTIVE_PROCESSES / running_pids / 日志文件全部挂在旧 id 上变孤儿。
    updated_project.id = project_id
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
    WATCHDOG_SUPPRESS.add(project_id)
    try:
        stop_project(project_id)
    except Exception:
        pass
    projects.pop(index)
    save_projects(projects)
    return {"success": True}


# ---------------------------------------------------------------------------
# Scenes — 把若干托管项目编成场景，按依赖顺序批量启动 / 逆序批量停止。
# 存储在 scenes.json（用户数据，gitignore），与 projects.json 的列表结构分离，
# 避免动老文件的格式。步骤里引用的项目 id 在启动时才解析，容忍"先建场景后建项目"。
# ---------------------------------------------------------------------------

SCENES_FILE = os.path.join(BASE_DIR, "scenes.json")
SCENES_LOCK = threading.Lock()


def load_scenes() -> List[dict]:
    if not os.path.exists(SCENES_FILE):
        return []
    try:
        with SCENES_LOCK:
            with open(SCENES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        return [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []
    except Exception:
        # 与 projects.json 同一策略：损坏时改名隔离，不静默吞
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            with SCENES_LOCK:
                os.replace(SCENES_FILE, f"{SCENES_FILE}.corrupt-{stamp}")
            print(f"scenes.json 已损坏，已隔离为 scenes.json.corrupt-{stamp}")
        except OSError:
            pass
        return []


def save_scenes(scenes: List[dict]):
    with SCENES_LOCK:
        atomic_write_json(SCENES_FILE, scenes)


def _coerce_scene_steps(steps) -> List[str]:
    """去重保序的项目 id 列表；顺序即启动顺序。"""
    out, seen = [], set()
    for s in (steps if isinstance(steps, list) else []):
        s = str(s).strip()
        if s and s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _scene_step_state(project_id: str, port) -> str:
    """场景视角的单步状态：managed / external / stopped。"""
    with PROC_LOCK:
        proc = ACTIVE_PROCESSES.get(project_id)
        if proc and proc.poll() is None:
            return "managed"
    entry = load_running_pids().get(project_id)
    if entry and is_pid_running(entry["pid"]) and _pid_matches_start(entry["pid"], entry.get("started_at")):
        return "managed"
    for p in get_active_system_ports():
        if p.get("port") == port:
            return "external"
    return "stopped"


def _get_scene_or_404(scene_id: str) -> dict:
    # 场景 id 与项目 id 共用同一套字符规则（同样要当 URL 片段）
    scene_id = validate_project_id(scene_id)
    scene = next((s for s in load_scenes() if s.get("id") == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@app.get("/api/scenes")
def get_scenes_api():
    projects = {p["id"]: p for p in load_projects()}
    out = []
    for scene in load_scenes():
        steps = []
        for pid in scene.get("steps", []):
            project = projects.get(pid)
            if not project:
                steps.append({"project_id": pid, "name": pid, "state": "missing"})
            else:
                state = _scene_step_state(pid, project.get("port"))
                steps.append({"project_id": pid, "name": project["name"], "state": state})
        up = sum(1 for s in steps if s["state"] in ("managed", "external"))
        out.append({"id": scene["id"], "name": scene.get("name", scene["id"]),
                    "steps": steps, "up_count": up, "total": len(steps)})
    return out


@app.get("/api/scenes/suggest")
def suggest_scenes():
    """自动检测"要一起启动才能用"的项目组合。

    信号：前端配置/.env 指向其他项目端口的 localhost 引用（vite proxy、
    API_URL…），以及去掉 -api/-web 等角色后缀后的同名项目。
    """
    projects = load_projects()
    port_by_id = {p["id"]: p.get("port") for p in projects}
    name_by_id = {p["id"]: p.get("name") or p["id"] for p in projects}
    # 命名配套必须喂 slug（id）：显示名可能是中文，剥不出 -api/-web 后缀
    groups = _detect_project_groups([
        {"id": p["id"], "name": p["id"], "cwd": p.get("cwd") or "",
         "port": p.get("port")}
        for p in projects
    ])
    out = []
    for g in groups:
        steps = [{"project_id": pid, "name": name_by_id.get(pid, pid),
                  "state": _scene_step_state(pid, port_by_id.get(pid))}
                 for pid in g["steps"]]
        out.append({"name": g["name"], "reason": g["reason"], "steps": steps})
    return {"groups": out}


@app.post("/api/scenes")
def create_scene(body: dict):
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    name = str(body.get("name") or "").strip()
    steps = _coerce_scene_steps(body.get("steps"))
    if not name or not steps:
        raise HTTPException(status_code=400, detail="Scene needs a name and at least one project step")
    scenes = load_scenes()
    base = slugify_project_id(name)
    scene_id, n = base, 1
    while any(s.get("id") == scene_id for s in scenes):
        n += 1
        scene_id = f"{base}-{n}"
    scenes.append({"id": scene_id, "name": name[:80], "steps": steps})
    save_scenes(scenes)
    return {"success": True, "scene": {"id": scene_id, "name": name, "steps": steps}}


@app.put("/api/scenes/{scene_id}")
def update_scene(scene_id: str, body: dict):
    scene = _get_scene_or_404(scene_id)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    name = str(body.get("name") or "").strip()
    steps = _coerce_scene_steps(body.get("steps"))
    if not name or not steps:
        raise HTTPException(status_code=400, detail="Scene needs a name and at least one project step")
    scenes = load_scenes()
    for s in scenes:
        if s.get("id") == scene["id"]:
            s["name"], s["steps"] = name[:80], steps
    save_scenes(scenes)
    return {"success": True, "scene": {"id": scene["id"], "name": name, "steps": steps}}


@app.delete("/api/scenes/{scene_id}")
def delete_scene(scene_id: str):
    scene = _get_scene_or_404(scene_id)
    save_scenes([s for s in load_scenes() if s.get("id") != scene["id"]])
    return {"success": True}


@app.post("/api/scenes/{scene_id}/start")
async def start_scene(scene_id: str):
    scene = _get_scene_or_404(scene_id)
    projects = {p["id"]: p for p in load_projects()}
    results = []
    for pid in scene.get("steps", []):
        project = projects.get(pid)
        if not project:
            results.append({"project_id": pid, "status": "missing"})
            return {"success": False, "results": results,
                    "error": f"步骤 {pid} 对应的项目已不存在，已中止（前面步骤保持运行）"}
        state = _scene_step_state(pid, project.get("port"))
        if state == "managed":
            results.append({"project_id": pid, "status": "already_running"})
            continue
        if state == "external":
            # 端口已被外部进程服务 → 依赖已就绪，跳过但如实标注
            results.append({"project_id": pid, "status": "external_serving"})
            continue
        try:
            r = await _start_project_core(project)
            results.append({"project_id": pid, "status": "started", "pid": r.get("pid")})
        except HTTPException as e:
            results.append({"project_id": pid, "status": "failed", "detail": str(e.detail)})
            invalidate_ports_cache()
            return {"success": False, "results": results,
                    "error": f"{project['name']}: {e.detail}"}
    invalidate_ports_cache()
    return {"success": True, "results": results,
            "message": f"Scene '{scene.get('name')}' started ({len(results)} steps)"}


@app.post("/api/scenes/{scene_id}/stop")
def stop_scene(scene_id: str):
    scene = _get_scene_or_404(scene_id)
    projects = {p["id"]: p for p in load_projects()}
    results = []
    for pid in reversed(scene.get("steps", [])):
        project = projects.get(pid)
        if not project:
            results.append({"project_id": pid, "status": "missing"})
            continue
        r = _stop_project_core(project)
        results.append({"project_id": pid,
                        "status": "stopped" if r.get("success") else "not_stopped",
                        "detail": r.get("message", "")})
    invalidate_ports_cache()
    return {"success": True, "results": results,
            "message": f"Scene '{scene.get('name')}' stopped ({len(results)} steps)"}


def _probe_health_url(health_url: str) -> bool:
    try:
        with urllib.request.urlopen(health_url, timeout=2) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, ConnectionError, OSError, TimeoutError):
        return False


async def _wait_for_startup(proc: subprocess.Popen, timeout_sec: int, health_url: str) -> Tuple[bool, str]:
    """
    Wait up to `timeout_sec` for `proc` to come up.

    If `health_url` is non-empty, polls it until a 2xx is seen or timeout.
    Otherwise just confirms the process didn't exit immediately.

    Returns (ok, error_message). On success error_message is empty.
    """
    deadline = time.time() + max(1, int(timeout_sec))
    poll_interval = 0.5

    while time.time() < deadline:
        # Did the child exit on its own? If so, startup failed.
        if proc.poll() is not None:
            return False, f"process exited with code {proc.returncode} before becoming ready"

        if not health_url:
            # No health URL: as soon as the process is still alive past the first
            # tick, treat it as started (matches previous "fire-and-forget" behavior).
            return True, ""

        if await asyncio.to_thread(_probe_health_url, health_url):
            return True, ""

        await asyncio.sleep(poll_interval)

    # Timed out.
    if health_url:
        return False, f"health check {health_url!r} did not return 2xx within {timeout_sec}s"
    return False, f"process did not stay alive within {timeout_sec}s"


def _kill_active_proc(project_id: str, proc: subprocess.Popen) -> None:
    """Best-effort kill of `proc` (and its children) plus state cleanup."""
    try:
        if proc.poll() is None:
            _kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    finally:
        with PROC_LOCK:
            ACTIVE_PROCESSES.pop(project_id, None)
            log_f = ACTIVE_LOG_FILES.pop(project_id, None)
        if log_f is not None:
            try:
                log_f.close()
            except Exception:
                pass


async def _start_project_core(project: dict) -> dict:
    """启动单个托管项目：状态检查 → 端口预检 → spawn → 健康检查 → 登记。

    手动启动路由与场景编排共用；失败抛 HTTPException，成功返回启动信息。
    """
    project_id = project["id"]
    snapshot = await asyncio.to_thread(get_projects_snapshot)
    current_state = next((p for p in snapshot if p["id"] == project_id), None)
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
    argv = _resolve_executable(argv)

    # Pre-flight: 检查目标端口是否已被外部进程占用（强制刷新端口快照，避免竞态）
    active_ports = await asyncio.to_thread(get_active_system_ports, True)
    port_conflict = next(
        (p for p in active_ports if p.get("port") == project["port"]),
        None,
    )
    if port_conflict:
        pid = port_conflict.get("pid")
        # 如果占用方在本面板管理的进程树里（含子孙进程），允许
        is_managed = bool(pid) and pid in _collect_managed_pids()
        if not is_managed:
            proc_name = port_conflict.get("process", "Unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Port {project['port']} is already in use by external process "
                    f"'{proc_name}' (PID {pid}). Stop it first or change the project's port.",
            )

    try:
        proc = _spawn_and_register(project, argv, env_overrides, log_mode="w")

        # Resolve startup timeout (clamp to 1..300s) and optional health URL.
        raw_timeout = project.get("startup_timeout_sec", 30)
        try:
            timeout_sec = int(raw_timeout)
        except (TypeError, ValueError):
            timeout_sec = 30
        timeout_sec = max(1, min(timeout_sec, 300))
        health_url = (project.get("health_check_url") or "").strip()

        ok, err = await _wait_for_startup(proc, timeout_sec, health_url)
        if not ok:
            _kill_active_proc(project_id, proc)
            append_log_line(project_id, "\n[startup check FAILED] " + err + "\n")
            raise HTTPException(
                status_code=500,
                detail=f"Project '{project['name']}' failed to become ready within {timeout_sec}s: {err}",
            )

        pids_map = load_running_pids()
        pids_map[project_id] = {
            "pid": proc.pid,
            "managed": True,
            # float 秒，供 _pid_matches_start 与 create_time 比对（PID 复用防护）
            "started_at": time.time(),
        }
        save_running_pids(pids_map)
        invalidate_ports_cache()
        # 手动启动解除看护抑制；期望状态在这里直接播种 —— 否则"两次巡检
        # 之间启动又崩溃"的进程永远不会被观察到活着，watchdog 不会拉起它。
        WATCHDOG_SUPPRESS.discard(project_id)
        WATCHDOG_STATE[project_id] = {"pid": proc.pid, "up_since": time.time(),
                                      "failures": 0, "next_retry_at": 0.0}
        return {"success": True, "pid": proc.pid, "message": f"Project '{project['name']}' started successfully"}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Executable not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start project: {str(e)}")


@app.post("/api/projects/{project_id}/start")
async def start_project(project_id: str):
    project_id = validate_project_id(project_id)
    project = next((p for p in load_projects() if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return await _start_project_core(project)


def _stop_project_core(project: dict) -> dict:
    """停止单个托管项目（手动路由与场景编排共用）。"""
    project_id = project["id"]

    current_state = next((p for p in get_projects_snapshot() if p["id"] == project_id), None)
    if current_state and current_state["status"] == "external":
        return {
            "success": False,
            "message": f"Project '{project['name']}' is currently running as an external process on port {project['port']}. Dashboard will not kill external processes automatically.",
            "external": True,
        }

    # 用户主动停止：即使项目开着 auto_restart，watchdog 也不得再拉起，
    # 直到下一次手动 start。未在运行的停止同样表达该意图。
    WATCHDOG_SUPPRESS.add(project_id)
    WATCHDOG_STATE.pop(project_id, None)

    pids_map = load_running_pids()
    entry = pids_map.get(project_id)
    pid = None
    with PROC_LOCK:
        proc = ACTIVE_PROCESSES.pop(project_id, None)
        log_file = ACTIVE_LOG_FILES.pop(project_id, None)
    if proc:
        pid = proc.pid
    elif entry:
        pid = entry["pid"]

    if log_file:
        try:
            log_file.close()
        except Exception:
            pass

    if not pid:
        return {"success": True, "message": "Project is not running (no managed process to stop)"}

    success = terminate_managed_pid(pid)
    pids_map.pop(project_id, None)
    save_running_pids(pids_map)
    invalidate_ports_cache()
    append_log_line(project_id, f"\n\n=== Project stopped at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    if success:
        return {"success": True, "message": f"Stopped managed project PID {pid}"}
    return {"success": False, "message": f"Could not stop managed process {pid} (it may have already exited)"}


@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str):
    project_id = validate_project_id(project_id)
    project = next((p for p in load_projects() if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _stop_project_core(project)


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
    """Tail-follow a log file, yielding SSE-formatted lines for each new chunk.

    行缓冲：按字节边界读到的 chunk 可能把一行从中间截断，直接 splitlines
    会把半行当整行推给前端。这里把不带换行的尾巴攒到下一轮再发；
    单行超过 64KB（畸形输出）时强制冲刷，防止内存无界。
    """
    last_pos = _initial_log_position(log_path)
    if last_pos is None:
        yield f"data: [synthetic] log file not found for {project_id}\n\n"
        return

    pending = b""
    while True:
        # 日志被截断重写（如 clear）时 last_pos 会大于文件大小，从头继续跟
        try:
            if os.path.getsize(log_path) < last_pos:
                last_pos = 0
                pending = b""
        except OSError:
            pass

        chunk = await _read_new_chunk(log_path, last_pos)
        if chunk is None:
            await asyncio.sleep(0.5)
            continue
        new_data, current_pos = chunk
        if new_data:
            last_pos = current_pos
            pending += new_data
            lines = pending.split(b"\n")
            pending = lines.pop()  # 最后一段是没有 \n 的尾巴，等下一轮
            for raw in lines:
                yield f"data: {_decode_sse_line(raw)}\n\n"
            if len(pending) > LOG_READ_CHUNK_SIZE:
                yield f"data: {_decode_sse_line(pending)}\n\n"
                pending = b""
        await asyncio.sleep(0.5)


def _decode_sse_line(raw: bytes) -> str:
    """Decode one raw log line into a single-line SSE-safe string."""
    return raw.decode("utf-8", errors="ignore").replace(chr(13), "").replace("\n", "\\n")


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
ALLOWED_TABS = {"managed", "local", "system"}
ALLOWED_REFRESH_INTERVALS = (3, 5, 10, 15, 30, 60)

DEFAULT_PREFERENCES = {
    "theme": "dark-emerald",
    "default_category": "user",
    "default_tab": "managed",
    "auto_refresh": True,
    "refresh_interval": 5,         # seconds
    "port": DEFAULT_PORT,          # binding port; takes effect after restart
}

# Resolved at import time (uvicorn re-imports this module, so setting it in
# __main__ would not propagate). Env var > preferences file > default.
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
    if raw.get("default_tab") in ALLOWED_TABS:
        out["default_tab"] = raw["default_tab"]
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


def _resolve_bind_port() -> int:
    """Env var > preferences file > 9229 default."""
    env_port = os.environ.get("MYDASHBOARD_PORT")
    if env_port and env_port.isdigit():
        return int(env_port)
    try:
        file_port = load_preferences().get("port")
        if isinstance(file_port, int) and 1 <= file_port <= 65535:
            return file_port
    except Exception:
        pass
    return DEFAULT_PORT


RUNNING_PORT = _resolve_bind_port()


@app.get("/api/preferences")
def get_preferences():
    """Return current preferences + the actually-running port."""
    prefs = load_preferences()
    return {
        "preferences": prefs,
        "running_port": RUNNING_PORT,
        "defaults": DEFAULT_PREFERENCES,
        "allowed": {
            "themes": sorted(ALLOWED_THEMES),
            "categories": sorted(ALLOWED_CATEGORIES),
            "tabs": sorted(ALLOWED_TABS),
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

    reload_enabled = os.environ.get("PORT_DASHBOARD_RELOAD", "0") == "1"
    # 默认只监听本机；需要局域网访问时显式设置 MYDASHBOARD_HOST=0.0.0.0
    bind_host = os.environ.get("MYDASHBOARD_HOST", "127.0.0.1")
    print(f"[mydashboard] binding to {bind_host}:{RUNNING_PORT} (set MYDASHBOARD_PORT/MYDASHBOARD_HOST to override)")
    uvicorn.run("app:app", host=bind_host, port=RUNNING_PORT, reload=reload_enabled)
