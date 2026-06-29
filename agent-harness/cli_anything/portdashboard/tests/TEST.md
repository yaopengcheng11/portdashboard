# Test Plan & Results — CLI-Anything Port Dashboard

## Test Inventory Plan

| File | Description | Planned Count |
|---|---|---|
| `test_core.py` | Unit tests (mocked HTTP, no dashboard required) | ~18 |
| `test_full_e2e.py` | E2E tests (requires running dashboard) | ~6 |

## Unit Test Plan (test_core.py)

### TestProject (8 tests)
- `test_list_projects` — mock API returns project list, verify parsing
- `test_get_project_found` — lookup existing project by ID
- `test_get_project_not_found` — returns None for unknown ID
- `test_create_project` — POST new project, verify success response
- `test_start_project` — POST start, verify PID returned
- `test_stop_project` — POST stop, verify success
- `test_get_logs` — GET logs with offset/limit
- `test_clear_logs` — POST clear, verify success

### TestPort (2 tests)
- `test_scan_ports` — mock API returns port list, verify parsing
- `test_kill_process` — POST kill PID, verify success

### TestSystem (2 tests)
- `test_get_stats` — mock API returns CPU/memory stats
- `test_get_snapshot` — mock API returns full dashboard snapshot

### TestCLIOutput (2 tests)
- `test_format_output_json` — JSON mode produces valid JSON
- `test_format_output_plain` — Plain mode produces readable string

### TestCLISubprocess (4 tests)
- `test_help` — `--help` exits 0, shows command groups
- `test_version` — `--version` shows 1.0.0
- `test_project_help` — `project --help` shows subcommands
- `test_port_help` — `port --help` shows subcommands

## E2E Test Plan (test_full_e2e.py)

Requires a running Port Dashboard at http://localhost:9229.

### TestCLISubprocessE2E (6 tests)
- `test_help` — basic help output
- `test_project_list_json` — list projects as JSON
- `test_port_scan_json` — scan ports as JSON, verify structure
- `test_system_stats_json` — system stats, verify CPU/memory fields
- `test_system_snapshot_json` — full snapshot with stats + ports + projects
- `test_full_project_lifecycle` — add → start → status → logs → stop → remove

## Workflow Scenarios

1. **Project lifecycle** - add project, start it, check status, read logs, stop it, remove it
2. **Port monitoring** - scan ports, identify external process, kill it
3. **System overview** - stats + snapshot for full system awareness

---

## Test Results

### Unit Tests (test_core.py)

```
platform win32 -- Python 3.13.5, pytest-9.1.1, pluggy-1.6.0

cli_anything/portdashboard/tests/test_core.py::TestProject::test_list_projects PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_get_project_found PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_get_project_not_found PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_create_project PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_start_project PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_stop_project PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_get_logs PASSED
cli_anything/portdashboard/tests/test_core.py::TestProject::test_clear_logs PASSED
cli_anything/portdashboard/tests/test_core.py::TestPort::test_scan_ports PASSED
cli_anything/portdashboard/tests/test_core.py::TestPort::test_kill_process PASSED
cli_anything/portdashboard/tests/test_core.py::TestSystem::test_get_stats PASSED
cli_anything/portdashboard/tests/test_core.py::TestSystem::test_get_snapshot PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLIOutput::test_format_output_json PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLIOutput::test_format_output_plain PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLISubprocess::test_help PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLISubprocess::test_version PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLISubprocess::test_project_help PASSED
cli_anything/portdashboard/tests/test_core.py::TestCLISubprocess::test_port_help PASSED

============================= 18 passed in 2.27s ==============================
```

### Summary

- **Total tests:** 18
- **Passed:** 18 (100%)
- **Failed:** 0
- **Execution time:** 2.27s
- **Coverage:** All core modules (project, port, system), CLI output formatting, subprocess CLI invocation
