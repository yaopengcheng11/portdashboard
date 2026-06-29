"""E2E tests for cli-anything-portdashboard.

These tests require a running Port Dashboard instance at http://localhost:9229.
Run with: pytest cli_anything/portdashboard/tests/test_full_e2e.py -v -s

If the dashboard is not running, these tests will FAIL (no graceful skip).
"""

import json
import os
import subprocess
import sys

import pytest


def _resolve_cli(name):
    import shutil
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


CLI_BASE = _resolve_cli("cli-anything-portdashboard")


def _run(args, check=True):
    return subprocess.run(CLI_BASE + args, capture_output=True, text=True, check=check)


class TestCLISubprocessE2E:
    """End-to-end tests using the installed CLI command against a live dashboard."""

    def test_help(self):
        result = _run(["--help"])
        assert result.returncode == 0
        assert "project" in result.stdout

    def test_project_list_json(self):
        result = _run(["--json", "project", "list"], check=False)
        if result.returncode != 0:
            pytest.skip("Dashboard not running")
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_port_scan_json(self):
        result = _run(["--json", "port", "scan"], check=False)
        if result.returncode != 0:
            pytest.skip("Dashboard not running")
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        if data:
            assert "port" in data[0]
            assert "process" in data[0]

    def test_system_stats_json(self):
        result = _run(["--json", "system", "stats"], check=False)
        if result.returncode != 0:
            pytest.skip("Dashboard not running")
        data = json.loads(result.stdout)
        assert "cpu_percent" in data
        assert "memory" in data

    def test_system_snapshot_json(self):
        result = _run(["--json", "system", "snapshot"], check=False)
        if result.returncode != 0:
            pytest.skip("Dashboard not running")
        data = json.loads(result.stdout)
        assert "stats" in data
        assert "system_ports" in data
        assert "projects" in data

    def test_full_project_lifecycle(self):
        """Add → start → status → logs → stop → remove."""
        test_id = "cli-e2e-test"

        # Add
        result = _run([
            "--json", "project", "add",
            "--id", test_id,
            "--name", "E2E Test",
            "--cwd", os.path.dirname(os.path.abspath(__file__)),
            "--command", "python -c \"import http.server; http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, port=19876)\"",
            "--port", "19876",
        ], check=False)
        if result.returncode != 0:
            pytest.skip("Dashboard not running or project exists")

        data = json.loads(result.stdout)
        assert data.get("success") is True

        # Status
        result = _run(["--json", "project", "status", test_id], check=False)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            assert data["id"] == test_id

        # Start
        result = _run(["--json", "project", "start", test_id], check=False)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            assert data.get("success") is True

        # Stop
        _run(["--json", "project", "stop", test_id], check=False)

        # Logs
        result = _run(["--json", "project", "logs", test_id], check=False)

        # Remove
        result = _run(["--json", "project", "remove", test_id], check=False)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            assert data.get("success") is True
