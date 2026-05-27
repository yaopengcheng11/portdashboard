import csv
import io
import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="MyDashboard - Port Control Center")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROJECTS_FILE = os.path.join(BASE_DIR, "projects.json")
RUNNING_PIDS_FILE = os.path.join(BASE_DIR, "running_pids.json")
WINDOWS_TASKLIST = "/mnt/c/Windows/System32/tasklist.exe"
WINDOWS_NETSTAT = "/mnt/c/Windows/System32/netstat.exe"
WINDOWS_TASKKILL = "/mnt/c/Windows/System32/taskkill.exe"
PORTS_CACHE_TTL = 3.0
WINDOWS_PORTS_CACHE_TTL = 15.0
STATS_CACHE_TTL = 2.0
LOG_READ_CHUNK_SIZE = 64 * 1024
CPU_SAMPLE_INTERVAL = 0.5
BACKGROUND_PORT_REFRESH_INTERVAL = 10.0

os.makedirs(LOGS_DIR, exist_ok=True)

ACTIVE_PROCESSES: Dict[str, subprocess.Popen] = {}
START_TIME = time.time()
PORTS_CACHE = {"timestamp": 0.0, "value": []}
WINDOWS_PORTS_CACHE = {"timestamp": 0.0, "value": []}
STATS_CACHE = {"timestamp": 0.0, "value": {}}
CPU_SAMPLE = {"timestamp": 0.0, "idle": 0.0, "total": 0.0, "percent": 0.0}
PROJECTS_LOCK = threading.Lock()
PIDS_LOCK = threading.Lock()
PORTS_CACHE_LOCK = threading.Lock()
PORTS_REFRESH_THREAD_STARTED = False


class Project(BaseModel):
    id: str
    name: str
    cwd: str
    command: str
    port: int
    description: Optional[str] = ""
    sync_name: bool = False


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


def run_command(command: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        check=False,
    )


def parse_wsl_ports() -> List[dict]:
    ports_info = []
    seen_ports = set()
    try:
        result = run_command(["ss", "-ltnp"], timeout=2.0)
        if result.returncode != 0:
            return ports_info
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            local_addr = parts[3]
            port_match = re.search(r':(\d+)$', local_addr)
            if not port_match:
                continue
            port = int(port_match.group(1))
            if port in seen_ports:
                continue
            proc_name = "Unknown"
            pid = None
            if len(parts) >= 6:
                proc_str = " ".join(parts[5:])
                pid_match = re.search(r'pid=(\d+)', proc_str)
                if pid_match:
                    pid = int(pid_match.group(1))
                name_match = re.search(r'users:\(\("([^"]+)"', proc_str) or re.search(r'\(\("([^"]+)"', proc_str)
                if name_match:
                    proc_name = name_match.group(1)
            ports_info.append(
                {
                    "address": local_addr,
                    "port": port,
                    "process": proc_name,
                    "pid": pid,
                    "status": "listening",
                    "platform": "wsl",
                }
            )
            seen_ports.add(port)
    except Exception as e:
        print(f"Error parsing WSL ports: {e}")
    return ports_info


def parse_windows_ports() -> List[dict]:
    ports_info = []
    seen_ports = set()
    try:
        pid_to_name = {}
        tasklist_result = run_command([WINDOWS_TASKLIST, "/FO", "CSV", "/NH"], timeout=2.0)
        if tasklist_result.returncode == 0:
            reader = csv.reader(io.StringIO(tasklist_result.stdout))
            for row in reader:
                if len(row) >= 2:
                    try:
                        pid_to_name[int(row[1])] = row[0]
                    except ValueError:
                        pass

        netstat_result = run_command([WINDOWS_NETSTAT, "-ano"], timeout=2.0)
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
            ports_info.append(
                {
                    "address": f"[Win] {local_addr}",
                    "port": port,
                    "process": f"[Win] {proc_name}",
                    "pid": pid,
                    "status": "listening",
                    "platform": "windows",
                }
            )
            seen_ports.add(port)
    except Exception as e:
        print(f"Error parsing Windows ports: {e}")
    return ports_info


def get_windows_ports(force_refresh: bool = False) -> List[dict]:
    now = time.time()
    with PORTS_CACHE_LOCK:
        if not force_refresh and now - WINDOWS_PORTS_CACHE["timestamp"] < WINDOWS_PORTS_CACHE_TTL:
            return list(WINDOWS_PORTS_CACHE["value"])

    windows_ports = parse_windows_ports()
    with PORTS_CACHE_LOCK:
        WINDOWS_PORTS_CACHE["timestamp"] = now
        WINDOWS_PORTS_CACHE["value"] = windows_ports
        return list(WINDOWS_PORTS_CACHE["value"])


def get_active_system_ports(force_refresh: bool = False) -> List[dict]:
    now = time.time()
    with PORTS_CACHE_LOCK:
        if not force_refresh and now - PORTS_CACHE["timestamp"] < PORTS_CACHE_TTL:
            return list(PORTS_CACHE["value"])

    ports_info = parse_wsl_ports() + get_windows_ports(force_refresh=force_refresh)
    ports_info.sort(key=lambda x: (x["port"], x["platform"]))
    with PORTS_CACHE_LOCK:
        PORTS_CACHE["timestamp"] = now
        PORTS_CACHE["value"] = ports_info
        return list(PORTS_CACHE["value"])


def invalidate_ports_cache():
    with PORTS_CACHE_LOCK:
        PORTS_CACHE["timestamp"] = 0.0
        WINDOWS_PORTS_CACHE["timestamp"] = 0.0


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


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


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


@app.on_event("startup")
def startup_event():
    readopt_processes()
    ensure_background_refresh_thread()
    invalidate_ports_cache()


def sample_cpu_percent() -> float:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            line = f.readline()
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return CPU_SAMPLE["percent"]
        vals = [float(x) for x in parts[1:8]]
        idle = vals[3] + vals[4]
        total = sum(vals)
        now = time.time()
        prev_total = CPU_SAMPLE["total"]
        prev_idle = CPU_SAMPLE["idle"]
        prev_timestamp = CPU_SAMPLE["timestamp"]
        if prev_total and now - prev_timestamp >= CPU_SAMPLE_INTERVAL:
            diff_idle = idle - prev_idle
            diff_total = total - prev_total
            if diff_total > 0:
                CPU_SAMPLE["percent"] = round((1.0 - diff_idle / diff_total) * 100, 1)
        CPU_SAMPLE["idle"] = idle
        CPU_SAMPLE["total"] = total
        CPU_SAMPLE["timestamp"] = now
    except Exception:
        pass
    return CPU_SAMPLE["percent"]


def get_system_stats_snapshot(force_refresh: bool = False) -> dict:
    now = time.time()
    if not force_refresh and now - STATS_CACHE["timestamp"] < STATS_CACHE_TTL and STATS_CACHE["value"]:
        return STATS_CACHE["value"]

    cpu_usage = sample_cpu_percent()

    mem_percent = 0.0
    mem_total_gb = 0.0
    mem_used_gb = 0.0
    try:
        mem_info = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2:
                    mem_info[p[0].rstrip(":")] = float(p[1])
        total = mem_info.get("MemTotal", 1.0)
        available = mem_info.get("MemAvailable")
        if available is None:
            free = mem_info.get("MemFree", 0.0)
            buffers = mem_info.get("Buffers", 0.0)
            cached = mem_info.get("Cached", 0.0)
            available = free + buffers + cached
        used = max(total - available, 0.0)
        mem_percent = round((used / total) * 100, 1)
        mem_total_gb = round(total / 1024 / 1024, 1)
        mem_used_gb = round(used / 1024 / 1024, 1)
    except Exception:
        pass

    wsl_ip = "127.0.0.1"
    try:
        result = run_command(["hostname", "-I"], timeout=1.0)
        ips = result.stdout.strip().split()
        if ips:
            wsl_ip = ips[0]
    except Exception:
        pass

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
        "ip_address": wsl_ip,
        "uptime": uptime_str,
        "os": "WSL (Ubuntu/Linux)",
    }
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


def get_dashboard_snapshot(force_refresh: bool = False) -> dict:
    ports = get_active_system_ports(force_refresh=force_refresh)
    return {
        "stats": get_system_stats_snapshot(force_refresh=force_refresh),
        "system_ports": ports,
        "projects": get_projects_snapshot(active_ports=ports),
        "generated_at": int(time.time() * 1000),
    }


def parse_command(command: str) -> Tuple[List[str], dict]:
    stripped = command.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    unsupported_shell_tokens = ["|", "&&", "||", ";", ">", "<", "$(", "`"]
    if any(token in stripped for token in unsupported_shell_tokens):
        raise HTTPException(
            status_code=400,
            detail="Command contains shell-only syntax. Please use a direct executable command without pipes, redirects, chaining, or subshells.",
        )

    try:
        parts = shlex.split(stripped)
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
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        return True
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except Exception:
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
            f"=== PORT DASHBOARD 提示 ===\n"
            f"项目 “{project['name']}”（端口 {project['port']}）目前处于【外部直接运行】状态。\n"
            f"它当前的系统 PID 是 {process.get('pid')} (程序名: '{process.get('process', 'Unknown')}')。\n\n"
            f"该进程不是由当前面板托管启动，因此无法捕获其控制台日志。\n\n"
            f"如果要在这里看日志，请先手动停止外部进程，再用面板重新启动该项目。"
        )
        return {"logs": logs, "next_offset": 0, "truncated": False, "synthetic": True}

    logs = (
        f"=== PORT DASHBOARD 提示 ===\n"
        f"项目 “{project['name']}”（端口 {project['port']}）当前处于【停止状态】。\n\n"
        f"尚未产生托管日志。点击“启动”后会开始记录输出。"
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
def kill_system_process(pid: int, platform: str = "wsl"):
    if pid <= 1:
        raise HTTPException(status_code=400, detail="Cannot kill system process 1")

    if platform == "windows":
        result = run_command([WINDOWS_TASKKILL, "/F", "/PID", str(pid)], timeout=3.0)
        if result.returncode == 0:
            invalidate_ports_cache()
            return {"success": True, "message": f"Successfully killed Windows process PID {pid}!"}
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or f"Failed to kill Windows process {pid}").strip())

    if terminate_managed_pid(pid):
        invalidate_ports_cache()
        return {"success": True, "message": f"Killed PID {pid}"}
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
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
    projects[index] = apply_project_display_name(updated_project.model_dump())
    save_projects(projects)
    return {"success": True, "project": updated_project}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
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
        log_file.write(f"Command: {' '.join(shlex.quote(part) for part in argv)}\n")
        if env_overrides:
            log_file.write(f"Env Overrides: {json.dumps(env_overrides, ensure_ascii=False)}\n")
        log_file.write("===========================================================\n\n")
        log_file.flush()

        sub_env = os.environ.copy()
        sub_env.update(env_overrides)
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["FORCE_COLOR"] = "1"

        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=sub_env,
        )

        ACTIVE_PROCESSES[project_id] = proc
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