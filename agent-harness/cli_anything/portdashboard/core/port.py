"""Port scanning and process management — wraps Port Dashboard port APIs."""

from cli_anything.portdashboard.core import api_get, api_post


def scan_ports() -> list:
    return api_get("/api/system/ports")


def kill_process(pid: int) -> dict:
    return api_post(f"/api/system/ports/kill/{pid}")
