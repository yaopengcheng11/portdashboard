"""System monitoring — wraps Port Dashboard system APIs."""

from cli_anything.portdashboard.core import api_get


def get_stats() -> dict:
    return api_get("/api/system/stats")


def get_snapshot(force: bool = False) -> dict:
    return api_get("/api/dashboard/snapshot", params={"force": force})
