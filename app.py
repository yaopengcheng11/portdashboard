import os
import sys
import json
import re
import signal
import time
import subprocess
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MyDashboard - Port Control Center")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories & Configuration Files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROJECTS_FILE = os.path.join(BASE_DIR, "projects.json")
RUNNING_PIDS_FILE = os.path.join(BASE_DIR, "running_pids.json")

# Ensure directories exist
os.makedirs(LOGS_DIR, exist_ok=True)

# In-memory registry for subprocesses spawned by *this* session
# Map: project_id -> subprocess.Popen
ACTIVE_PROCESSES = {}
START_TIME = time.time()

# Models
class Project(BaseModel):
    id: str
    name: str
    cwd: str
    command: str
    port: int
    description: Optional[str] = ""

# Load / Save Helpers
def load_projects() -> List[dict]:
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_projects(projects: List[dict]):
    with open(PROJECTS_FILE, "w") as f:
        json.dump(projects, f, indent=2)

def load_running_pids() -> dict:
    if not os.path.exists(RUNNING_PIDS_FILE):
        return {}
    try:
        with open(RUNNING_PIDS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_running_pids(pids: dict):
    with open(RUNNING_PIDS_FILE, "w") as f:
        json.dump(pids, f, indent=2)

# Helper: Parse active listening ports from both WSL (`ss -ltnp`) and Windows (`netstat.exe -ano`)
def get_active_system_ports() -> List[dict]:
    ports_info = []
    
    # 1. Fetch WSL ports
    try:
        # Run ss -ltnp to get listening TCP ports with process details
        result = subprocess.run(
            ["ss", "-ltnp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            # Parse output
            for line in lines[1:]:
                parts = line.split()
                if len(parts) < 4:
                    continue
                
                local_addr = parts[3]
                # Extract port
                port_match = re.search(r':(\d+)$', local_addr)
                if not port_match:
                    continue
                port = int(port_match.group(1))
                
                # Extract process details (PID & Name)
                proc_name = "Unknown"
                pid = None
                if len(parts) >= 6:
                    proc_str = " ".join(parts[5:])
                    pid_match = re.search(r'pid=(\d+)', proc_str)
                    if pid_match:
                        pid = int(pid_match.group(1))
                    name_match = re.search(r'users:\(\("([^"]+)"', proc_str)
                    if name_match:
                        proc_name = name_match.group(1)
                    else:
                        name_match2 = re.search(r'\(\("([^"]+)"', proc_str)
                        if name_match2:
                            proc_name = name_match2.group(1)
                
                # Check if this port is already added to avoid duplicates in list
                if not any(p["port"] == port and p.get("platform") == "wsl" for p in ports_info):
                    ports_info.append({
                        "address": local_addr,
                        "port": port,
                        "process": proc_name,
                        "pid": pid,
                        "status": "listening",
                        "platform": "wsl"
                    })
    except Exception as e:
        print(f"Error parsing WSL ports: {e}")

    # 2. Fetch Windows ports
    try:
        # Get process names mapping
        pid_to_name = {}
        res = subprocess.run(
            ["/mnt/c/Windows/System32/tasklist.exe", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=2.0
        )
        if res.returncode == 0:
            import csv
            import io
            reader = csv.reader(io.StringIO(res.stdout))
            for row in reader:
                if len(row) >= 2:
                    name = row[0]
                    pid = row[1]
                    try:
                        pid_to_name[int(pid)] = name
                    except ValueError:
                        pass

        # Get netstat
        res = subprocess.run(
            ["/mnt/c/Windows/System32/netstat.exe", "-ano"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=2.0
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split("\n")
            for line in lines:
                if "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        proto = parts[0]
                        local_addr = parts[1]
                        state = parts[3]
                        pid_str = parts[4]
                        
                        port_match = re.search(r':(\d+)$', local_addr)
                        if port_match:
                            port = int(port_match.group(1))
                            try:
                                pid = int(pid_str)
                            except ValueError:
                                pid = None
                            
                            proc_name = pid_to_name.get(pid, "Unknown") if pid else "Unknown"
                            
                            # Avoid duplicates and clearly distinguish
                            if not any(p["port"] == port and p.get("platform") == "windows" for p in ports_info):
                                ports_info.append({
                                    "address": f"[Win] {local_addr}",
                                    "port": port,
                                    "process": f"[Win] {proc_name}",
                                    "pid": pid,
                                    "status": "listening",
                                    "platform": "windows"
                                })
    except Exception as e:
        print(f"Error parsing Windows ports: {e}")

    # Sort ports numerically
    ports_info.sort(key=lambda x: x["port"])
    return ports_info

# Helper: Check if process is running by PID
def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

# Re-adopt previously running processes on startup
def readopt_processes():
    pids_map = load_running_pids()
    updated_pids_map = {}
    for proj_id, pid in pids_map.items():
        if is_pid_running(pid):
            updated_pids_map[proj_id] = pid
            print(f"Re-adopted running project {proj_id} with PID {pid}")
        else:
            print(f"Project {proj_id} with PID {pid} is no longer running")
    save_running_pids(updated_pids_map)

# Startup event
@app.on_event("startup")
def startup_event():
    readopt_processes()

# REST APIs

@app.get("/api/system/stats")
def get_system_stats():
    # Get CPU Usage
    cpu_usage = 0.0
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        parts = line.split()
        if parts and parts[0] == "cpu":
            vals = [float(x) for x in parts[1:8]]
            idle1 = vals[3] + vals[4]
            total1 = sum(vals)
            time.sleep(0.05)
            with open("/proc/stat", "r") as f:
                line2 = f.readline()
            parts2 = line2.split()
            if parts2 and parts2[0] == "cpu":
                vals2 = [float(x) for x in parts2[1:8]]
                idle2 = vals2[3] + vals2[4]
                total2 = sum(vals2)
                diff_idle = idle2 - idle1
                diff_total = total2 - total1
                if diff_total != 0:
                    cpu_usage = round((1.0 - diff_idle / diff_total) * 100, 1)
    except Exception:
        pass

    # Get Memory Usage
    mem_percent = 0.0
    mem_total_gb = 0.0
    mem_used_gb = 0.0
    try:
        mem_info = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2:
                    mem_info[p[0].rstrip(":")] = float(p[1])
        total = mem_info.get("MemTotal", 1.0)
        free = mem_info.get("MemFree", 0.0)
        buffers = mem_info.get("Buffers", 0.0)
        cached = mem_info.get("Cached", 0.0)
        used = total - free - buffers - cached
        mem_percent = round((used / total) * 100, 1)
        mem_total_gb = round(total / 1024 / 1024, 1)
        mem_used_gb = round(used / 1024 / 1024, 1)
    except Exception:
        pass

    # Get WSL IP
    wsl_ip = "127.0.0.1"
    try:
        result = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE, text=True)
        ips = result.stdout.strip().split()
        if ips:
            wsl_ip = ips[0]
    except Exception:
        pass

    uptime_sec = time.time() - START_TIME
    uptime_str = ""
    if uptime_sec < 60:
        uptime_str = f"{int(uptime_sec)}s"
    elif uptime_sec < 3600:
        uptime_str = f"{int(uptime_sec // 60)}m {int(uptime_sec % 60)}s"
    else:
        uptime_str = f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m"

    return {
        "cpu_percent": cpu_usage,
        "memory": {
            "percent": mem_percent,
            "total_gb": mem_total_gb,
            "used_gb": mem_used_gb
        },
        "ip_address": wsl_ip,
        "uptime": uptime_str,
        "os": "WSL (Ubuntu/Linux)"
    }

@app.get("/api/system/ports")
def get_system_ports():
    return get_active_system_ports()

@app.post("/api/system/ports/kill/{pid}")
def kill_system_process(pid: int, platform: str = "wsl"):
    if pid <= 1:
        raise HTTPException(status_code=400, detail="Cannot kill system process 1")
    
    if platform == "windows":
        try:
            # Kill Windows process using taskkill.exe /F /PID
            result = subprocess.run(
                ["/mnt/c/Windows/System32/taskkill.exe", "/F", "/PID", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            return {"success": True, "message": f"Successfully killed Windows process PID {pid}!"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to kill Windows process {pid}: {str(e)}")

    try:
        # Try killing process group first
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        return {"success": True, "message": f"Killed process group PGID {pgid} (PID {pid})"}
    except Exception:
        try:
            # Fallback to direct kill
            os.kill(pid, signal.SIGKILL)
            return {"success": True, "message": f"Killed PID {pid}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to kill process {pid}: {str(e)}")

@app.get("/api/projects")
def get_projects_api():
    projects = load_projects()
    active_ports = get_active_system_ports()
    pids_map = load_running_pids()
    
    enhanced_projects = []
    for proj in projects:
        proj_id = proj["id"]
        target_port = proj["port"]
        
        # Check active ports matching target port
        port_match = next((p for p in active_ports if p["port"] == target_port), None)
        
        status = "stopped"
        current_pid = None
        process_owner = "Unknown"
        
        # 1. Check if we have an active process spawned in *this* FastAPI session
        if proj_id in ACTIVE_PROCESSES:
            proc = ACTIVE_PROCESSES[proj_id]
            if proc.poll() is None:  # Process is running
                status = "running"
                current_pid = proc.pid
                process_owner = "Dashboard"
            else:
                # Process exited
                ACTIVE_PROCESSES.pop(proj_id)
                if proj_id in pids_map:
                    pids_map.pop(proj_id)
                    save_running_pids(pids_map)
        
        # 2. Check if we re-adopted a running PID from a previous dashboard session
        if status == "stopped" and proj_id in pids_map:
            saved_pid = pids_map[proj_id]
            if is_pid_running(saved_pid):
                status = "running"
                current_pid = saved_pid
                process_owner = "Dashboard (Adopted)"
            else:
                pids_map.pop(proj_id)
                save_running_pids(pids_map)
                
        # 3. Check if *any* process is listening on the target port
        if status == "stopped" and port_match:
            status = "running"
            current_pid = port_match["pid"]
            process_owner = f"External ({port_match['process']})"
            
        enhanced_projects.append({
            **proj,
            "status": status,
            "pid": current_pid,
            "owner": process_owner,
            "port_active": port_match is not None
        })
        
    return enhanced_projects

@app.post("/api/projects")
def create_project(project: Project):
    projects = load_projects()
    if any(p["id"] == project.id for p in projects):
        raise HTTPException(status_code=400, detail="Project ID already exists")
    if any(p["port"] == project.port for p in projects):
        # We allow multiple projects on same port in list, but issue a warning or let it pass
        pass
        
    projects.append(project.dict())
    save_projects(projects)
    return {"success": True, "project": project}

@app.put("/api/projects/{project_id}")
def update_project(project_id: str, updated_project: Project):
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
        
    projects[index] = updated_project.dict()
    save_projects(projects)
    return {"success": True, "project": updated_project}

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    projects = load_projects()
    index = next((i for i, p in enumerate(projects) if p["id"] == project_id), -1)
    if index == -1:
        raise HTTPException(status_code=404, detail="Project not found")
        
    # Stop first if running
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
        
    # Check if target port is already occupied
    active_ports = get_active_system_ports()
    occupied = next((p for p in active_ports if p["port"] == project["port"]), None)
    if occupied:
        raise HTTPException(
            status_code=400, 
            detail=f"Port {project['port']} is already occupied by process '{occupied['process']}' (PID {occupied['pid']}). Please stop it first."
        )
        
    # Verify working directory
    cwd = project["cwd"]
    if not os.path.exists(cwd):
        raise HTTPException(status_code=400, detail=f"Working directory does not exist: {cwd}")
        
    # Setup log file
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    
    try:
        # Open log file (overwrite for fresh logs)
        log_file = open(log_path, "w")
        log_file.write(f"=== Starting project '{project['name']}' at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log_file.write(f"CWD: {cwd}\n")
        log_file.write(f"Command: {project['command']}\n")
        log_file.write(f"===========================================================\n\n")
        log_file.flush()
        
        # Inject environment variables to force unbuffered output and ANSI colors
        sub_env = os.environ.copy()
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["FORCE_COLOR"] = "1"
        
        # Start background subprocess with os.setsid to create a process group
        proc = subprocess.Popen(
            project["command"],
            shell=True,
            cwd=cwd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=sub_env
        )
        
        # Store in registries
        ACTIVE_PROCESSES[project_id] = proc
        pids_map = load_running_pids()
        pids_map[project_id] = proc.pid
        save_running_pids(pids_map)
        
        return {"success": True, "pid": proc.pid, "message": f"Project '{project['name']}' started successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start project: {str(e)}")

@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str):
    # 1. Check if we have active tracker in memory
    proc = ACTIVE_PROCESSES.get(project_id)
    pid = None
    
    if proc:
        pid = proc.pid
        ACTIVE_PROCESSES.pop(project_id)
    else:
        # Check saved PIDs
        pids_map = load_running_pids()
        pid = pids_map.get(project_id)
        if pid:
            pids_map.pop(project_id)
            save_running_pids(pids_map)
            
    # If no PID found, let's look up by project's port
    if not pid:
        projects = load_projects()
        project = next((p for p in projects if p["id"] == project_id), None)
        if project:
            active_ports = get_active_system_ports()
            port_match = next((p for p in active_ports if p["port"] == project["port"]), None)
            if port_match:
                pid = port_match["pid"]
                
    if not pid:
        return {"success": True, "message": "Project is not running (no process to stop)"}
        
    # Terminate process group
    success = False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        success = True
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
            success = True
        except Exception:
            pass
            
    # Record stopping in logs
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "a") as f:
                f.write(f"\n\n=== Project stopped at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            pass
            
    if success:
        return {"success": True, "message": f"Stopped project with PID {pid}"}
    else:
        return {"success": False, "message": f"Could not stop process {pid} (it may have already exited)"}

@app.get("/api/projects/{project_id}/logs")
def get_project_logs(project_id: str, limit: int = 200):
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    
    if not os.path.exists(log_path):
        # Read status to give friendly tip
        projects = load_projects()
        project = next((p for p in projects if p["id"] == project_id), None)
        if project:
            active_ports = get_active_system_ports()
            port_match = next((p for p in active_ports if p["port"] == project["port"]), None)
            
            # Check if running externally or stopped
            is_managed_alive = False
            if project_id in ACTIVE_PROCESSES:
                is_managed_alive = ACTIVE_PROCESSES[project_id].poll() is None
            else:
                pids_map = load_running_pids()
                if project_id in pids_map:
                    is_managed_alive = is_pid_running(pids_map[project_id])
                    
            if not is_managed_alive and port_match:
                # Running externally
                return {
                    "logs": (
                        f"=== 🎙️ PORT DASHBOARD 提示 ===\n"
                        f"项目 “{project['name']}”（端口 {project['port']}）目前处于【外部直接运行】状态。\n"
                        f"它当前的系统 PID 是 {port_match['pid']} (程序名: '{port_match['process']}')。\n\n"
                        f"由于该程序是您在此面板外部启动的（比如在另一个黑窗口手动运行了程序），本控制中心没有代理该进程，因此无法捕获到它的控制台输出日志。\n\n"
                        f"💡 【如何解决？】\n"
                        f"如果您想在网页中查看其输出日志：\n"
                        f"1. 点击卡片下方的 “关闭” 按钮，通过面板强杀并关闭当前运行的外部程序。\n"
                        f"2. 紧接着点击 “启动” 按钮。这样它将彻底被控制中心托管，您就能在此实时看到所有的控制台日志了！"
                    )
                }
            elif not is_managed_alive:
                # Stopped
                return {
                    "logs": (
                        f"=== 🎙️ PORT DASHBOARD 提示 ===\n"
                        f"项目 “{project['name']}”（端口 {project['port']}）当前正处于【停止状态】。\n\n"
                        f"由于该项目目前未被启动，也没有任何外部进程占用该端口，因此尚未产生任何运行日志。\n\n"
                        f"💡 【如何运行？】\n"
                        f"直接点击该项目卡片下方的 “启动” 按钮，服务成功运行后，日志终端将立刻开始投射其实时输出！"
                    )
                }
        return {"logs": f"No log file found for project {project_id} yet."}
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        recent_lines = lines[-limit:]
        return {"logs": "".join(recent_lines)}
    except Exception as e:
        return {"logs": f"Error reading log file: {str(e)}"}

@app.post("/api/projects/{project_id}/logs/clear")
def clear_project_logs(project_id: str):
    log_path = os.path.join(LOGS_DIR, f"{project_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "w") as f:
                f.write(f"=== Logs cleared at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear logs: {str(e)}")
    return {"success": True}

# Serve single-page dashboard app
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
    # Use standard host and default port 9229 so it doesn't conflict with anything
    uvicorn.run("app:app", host="0.0.0.0", port=9229, reload=True)
