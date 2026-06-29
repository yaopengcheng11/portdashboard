"""Project lifecycle management — wraps Port Dashboard project APIs."""

from cli_anything.portdashboard.core import api_get, api_post, api_put, api_delete


def list_projects() -> list:
    return api_get("/api/projects")


def get_project(project_id: str) -> dict:
    projects = api_get("/api/projects")
    for p in projects:
        if p["id"] == project_id:
            return p
    return None


def create_project(project_id: str, name: str, cwd: str, command: str, port: int, description: str = "", sync_name: bool = False) -> dict:
    data = {
        "id": project_id,
        "name": name,
        "cwd": cwd,
        "command": command,
        "port": port,
        "description": description,
        "sync_name": sync_name,
    }
    return api_post("/api/projects", data)


def update_project(project_id: str, name: str, cwd: str, command: str, port: int, description: str = "", sync_name: bool = False) -> dict:
    data = {
        "id": project_id,
        "name": name,
        "cwd": cwd,
        "command": command,
        "port": port,
        "description": description,
        "sync_name": sync_name,
    }
    return api_put(f"/api/projects/{project_id}", data)


def delete_project(project_id: str) -> dict:
    return api_delete(f"/api/projects/{project_id}")


def start_project(project_id: str) -> dict:
    return api_post(f"/api/projects/{project_id}/start")


def stop_project(project_id: str) -> dict:
    return api_post(f"/api/projects/{project_id}/stop")


def get_logs(project_id: str, offset: int = 0, limit: int = 65536) -> dict:
    return api_get(f"/api/projects/{project_id}/logs", params={"offset": offset, "limit": limit})


def clear_logs(project_id: str) -> dict:
    return api_post(f"/api/projects/{project_id}/logs/clear")
