"""Unit tests for CLI-anything-portdashboard core modules.

Tests use mocked HTTP responses — no running dashboard required.
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────

MOCK_PROJECTS = [
    {
        "id": "test-app",
        "name": "Test App",
        "cwd": "G:/projects/test-app",
        "command": "npm run dev",
        "port": 3000,
        "description": "A test project",
        "sync_name": False,
        "status": "stopped",
        "pid": None,
        "owner": "Unknown",
        "port_active": False,
        "managed": False,
    },
    {
        "id": "api-server",
        "name": "API Server",
        "cwd": "G:/projects/api",
        "command": "python app.py",
        "port": 8000,
        "description": "",
        "sync_name": True,
        "status": "running",
        "pid": 12345,
        "owner": "Dashboard",
        "port_active": True,
        "managed": True,
    },
]

MOCK_PORTS = [
    {"address": "0.0.0.0:3000", "port": 3000, "process": "node.exe", "pid": 5000, "status": "listening", "platform": "windows"},
    {"address": "127.0.0.1:8000", "port": 8000, "process": "python.exe", "pid": 12345, "status": "listening", "platform": "windows"},
    {"address": "0.0.0.0:9229", "port": 9229, "process": "python.exe", "pid": 9999, "status": "listening", "platform": "windows"},
]

MOCK_STATS = {
    "cpu_percent": 25.3,
    "memory": {"percent": 62.1, "total_gb": 32.0, "used_gb": 19.9},
    "ip_address": "192.168.1.100",
    "uptime": "2h 15m",
    "os": "Windows",
}


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.raise_for_status = MagicMock()
    return resp


# ── Project tests ─────────────────────────────────────────────────────────

class TestProject:
    @patch("cli_anything.portdashboard.core.requests")
    def test_list_projects(self, mock_requests):
        mock_requests.get.return_value = _mock_response(MOCK_PROJECTS)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import list_projects
        result = list_projects()
        assert len(result) == 2
        assert result[0]["id"] == "test-app"
        assert result[1]["status"] == "running"

    @patch("cli_anything.portdashboard.core.requests")
    def test_get_project_found(self, mock_requests):
        mock_requests.get.return_value = _mock_response(MOCK_PROJECTS)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import get_project
        result = get_project("test-app")
        assert result is not None
        assert result["name"] == "Test App"
        assert result["port"] == 3000

    @patch("cli_anything.portdashboard.core.requests")
    def test_get_project_not_found(self, mock_requests):
        mock_requests.get.return_value = _mock_response(MOCK_PROJECTS)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import get_project
        result = get_project("nonexistent")
        assert result is None

    @patch("cli_anything.portdashboard.core.requests")
    def test_create_project(self, mock_requests):
        expected = {"success": True, "project": {"id": "new-app", "name": "New App"}}
        mock_requests.post.return_value = _mock_response(expected)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import create_project
        result = create_project("new-app", "New App", "G:/projects/new", "npm start", 4000)
        assert result["success"] is True

    @patch("cli_anything.portdashboard.core.requests")
    def test_start_project(self, mock_requests):
        expected = {"success": True, "pid": 54321, "message": "Project 'Test App' started successfully"}
        mock_requests.post.return_value = _mock_response(expected)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import start_project
        result = start_project("test-app")
        assert result["success"] is True
        assert result["pid"] == 54321

    @patch("cli_anything.portdashboard.core.requests")
    def test_stop_project(self, mock_requests):
        expected = {"success": True, "message": "Stopped managed project PID 12345"}
        mock_requests.post.return_value = _mock_response(expected)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import stop_project
        result = stop_project("api-server")
        assert result["success"] is True

    @patch("cli_anything.portdashboard.core.requests")
    def test_get_logs(self, mock_requests):
        expected = {"logs": "Server started on port 3000\n", "next_offset": 30, "truncated": False, "synthetic": False}
        mock_requests.get.return_value = _mock_response(expected)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import get_logs
        result = get_logs("test-app")
        assert "Server started" in result["logs"]

    @patch("cli_anything.portdashboard.core.requests")
    def test_clear_logs(self, mock_requests):
        mock_requests.post.return_value = _mock_response({"success": True})
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.project import clear_logs
        result = clear_logs("test-app")
        assert result["success"] is True


# ── Port tests ────────────────────────────────────────────────────────────

class TestPort:
    @patch("cli_anything.portdashboard.core.requests")
    def test_scan_ports(self, mock_requests):
        mock_requests.get.return_value = _mock_response(MOCK_PORTS)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.port import scan_ports
        result = scan_ports()
        assert len(result) == 3
        assert result[0]["port"] == 3000
        assert result[1]["process"] == "python.exe"

    @patch("cli_anything.portdashboard.core.requests")
    def test_kill_process(self, mock_requests):
        expected = {"success": True, "message": "Killed process PID 5000"}
        mock_requests.post.return_value = _mock_response(expected)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.port import kill_process
        result = kill_process(5000)
        assert result["success"] is True


# ── System tests ──────────────────────────────────────────────────────────

class TestSystem:
    @patch("cli_anything.portdashboard.core.requests")
    def test_get_stats(self, mock_requests):
        mock_requests.get.return_value = _mock_response(MOCK_STATS)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.system import get_stats
        result = get_stats()
        assert result["cpu_percent"] == 25.3
        assert result["memory"]["total_gb"] == 32.0
        assert result["os"] == "Windows"

    @patch("cli_anything.portdashboard.core.requests")
    def test_get_snapshot(self, mock_requests):
        snapshot = {
            "stats": MOCK_STATS,
            "system_ports": MOCK_PORTS,
            "projects": MOCK_PROJECTS,
            "generated_at": 1234567890000,
        }
        mock_requests.get.return_value = _mock_response(snapshot)
        mock_requests.ConnectionError = ConnectionError

        from cli_anything.portdashboard.core.system import get_snapshot
        result = get_snapshot()
        assert "stats" in result
        assert "system_ports" in result
        assert "projects" in result
        assert len(result["projects"]) == 2


# ── CLI output tests ─────────────────────────────────────────────────────

class TestCLIOutput:
    def test_format_output_json(self):
        from cli_anything.portdashboard.core import format_output
        data = {"key": "value"}
        result = format_output(data, as_json=True)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_format_output_plain(self):
        from cli_anything.portdashboard.core import format_output
        result = format_output({"key": "value"}, as_json=False)
        assert "key" in result


class TestCLISubprocess:
    """Test the installed CLI command via subprocess."""

    def _resolve_cli(self, name):
        import shutil
        force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
        path = shutil.which(name)
        if path:
            return [path]
        if force:
            raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
        import sys
        module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
        return [sys.executable, "-m", module]

    def test_help(self):
        import subprocess
        cli_base = self._resolve_cli("cli-anything-portdashboard")
        result = subprocess.run(cli_base + ["--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "project" in result.stdout
        assert "port" in result.stdout
        assert "system" in result.stdout

    def test_version(self):
        import subprocess
        cli_base = self._resolve_cli("cli-anything-portdashboard")
        result = subprocess.run(cli_base + ["--version"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "1.0.0" in result.stdout

    def test_project_help(self):
        import subprocess
        cli_base = self._resolve_cli("cli-anything-portdashboard")
        result = subprocess.run(cli_base + ["project", "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "list" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout

    def test_port_help(self):
        import subprocess
        cli_base = self._resolve_cli("cli-anything-portdashboard")
        result = subprocess.run(cli_base + ["port", "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "scan" in result.stdout
        assert "kill" in result.stdout
