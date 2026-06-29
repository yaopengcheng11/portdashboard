# CLI-Anything Port Dashboard

Agent-native CLI for [Port Dashboard](../../README.md) — a local port monitoring and service management dashboard.

## Prerequisites

- Python 3.10+
- Port Dashboard must be running (`start.bat` or `python app.py`)
- The dashboard runs on `http://localhost:9229` by default

## Installation

```bash
cd G:\AITools\portdashboard\agent-harness
pip install -e .
```

Verify:

```bash
cli-anything-portdashboard --help
```

## Usage

### One-shot commands

```bash
# List all managed projects
cli-anything-portdashboard project list

# Scan active ports
cli-anything-portdashboard port scan

# System stats
cli-anything-portdashboard system stats

# Full dashboard snapshot (JSON for agent consumption)
cli-anything-portdashboard --json system snapshot

# Start/stop a project
cli-anything-portdashboard project start my-app
cli-anything-portdashboard project stop my-app

# View project logs
cli-anything-portdashboard project logs my-app
```

### REPL mode (interactive)

```bash
cli-anything-portdashboard
# Enters interactive mode — type 'help' for commands
```

### JSON output (for agents)

Every command supports `--json`:

```bash
cli-anything-portdashboard --json project list
cli-anything-portdashboard --json port scan
cli-anything-portdashboard --json system stats
```

## Running Tests

```bash
cd G:\AITools\portdashboard\agent-harness
pip install -e ".[repl]" pytest
pytest cli_anything/portdashboard/tests/ -v
```

## Command Reference

| Command | Description |
|---|---|
| `project list` | List all projects with runtime status |
| `project add` | Add a new project (--id, --name, --cwd, --command, --port) |
| `project update` | Update project configuration |
| `project remove` | Remove a project |
| `project start <id>` | Start a project |
| `project stop <id>` | Stop a running project |
| `project status <id>` | Show project details |
| `project logs <id>` | View console logs |
| `project logs-clear <id>` | Clear logs |
| `port scan` | Scan active TCP listening ports |
| `port kill <pid>` | Kill a process by PID |
| `system stats` | CPU and memory usage |
| `system snapshot` | Full dashboard snapshot |
| `open` | Open dashboard in browser |

## Configuration

Set `PORT_DASHBOARD_URL` environment variable if the dashboard is not on the default port:

```bash
export PORT_DASHBOARD_URL=http://localhost:8080
cli-anything-portdashboard project list
```
