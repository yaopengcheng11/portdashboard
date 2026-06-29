---
name: "cli-anything-portdashboard"
description: "Agent-native CLI for Port Dashboard — manage local services, scan ports, monitor system stats, control project lifecycles via command line"
version: "1.0.0"
software: "Port Dashboard"
software_type: "web-dashboard"
platform: ["Windows"]
---

# CLI-Anything Port Dashboard

Agent-native CLI for [Port Dashboard](https://github.com/user/portdashboard) — a local port monitoring and service management dashboard running on FastAPI.

## Prerequisites

- **Port Dashboard** must be running at `http://localhost:9229` (default)
- Python 3.10+ with `click` and `requests` packages

## Installation

```bash
pip install cli-anything-portdashboard
```

Or from source:

```bash
cd portdashboard/agent-harness
pip install -e .
```

## Quick Start

```bash
# Interactive REPL (default)
cli-anything-portdashboard

# One-shot commands
cli-anything-portdashboard project list
cli-anything-portdashboard port scan
cli-anything-portdashboard system stats

# JSON output for agent consumption
cli-anything-portdashboard --json project list
cli-anything-portdashboard --json system snapshot
```

## Command Groups

### `project` — Project Lifecycle Management

| Command | Description |
|---|---|
| `project list` | List all managed projects with runtime status |
| `project add --id ID --name NAME --cwd DIR --command CMD --port PORT` | Register a new project |
| `project update ID --name NAME --cwd DIR --command CMD --port PORT` | Update project configuration |
| `project remove ID` | Remove a project |
| `project start ID` | Start a project process |
| `project stop ID` | Stop a running project |
| `project status ID` | Show detailed project status |
| `project logs ID [--offset N] [--limit N]` | View console logs |
| `project logs-clear ID` | Clear console logs |

### `port` — Port Scanning & Process Management

| Command | Description |
|---|---|
| `port scan` | Scan all active TCP listening ports |
| `port kill PID` | Kill a process by PID |

### `system` — System Monitoring

| Command | Description |
|---|---|
| `system stats` | Show CPU and memory usage |
| `system snapshot [--force]` | Full dashboard snapshot (stats + ports + projects) |

### Other

| Command | Description |
|---|---|
| `open` | Open dashboard UI in browser |

## Agent Guidance

### Always use `--json` for programmatic usage

```bash
# Get all projects as JSON array
cli-anything-portdashboard --json project list

# Get full system snapshot
cli-anything-portdashboard --json system snapshot
```

JSON output structure for `project list`:
```json
[
  {
    "id": "my-app",
    "name": "My App",
    "port": 3000,
    "status": "running",    // "running" | "stopped" | "external"
    "pid": 12345,
    "owner": "Dashboard",   // "Dashboard" | "Dashboard (Adopted)" | "External (...)"
    "managed": true
  }
]
```

### Configuration

Override the dashboard URL via environment variable:

```bash
PORT_DASHBOARD_URL=http://localhost:8080 cli-anything-portdashboard project list
```

### Common Workflows

**Check if a port is available:**
```bash
cli-anything-portdashboard --json port scan | python -c "import sys,json; ports=[p['port'] for p in json.load(sys.stdin)]; print(3000 in ports)"
```

**Start a project and tail logs:**
```bash
cli-anything-portdashboard project start my-app
cli-anything-portdashboard project logs my-app
```

**Full system overview:**
```bash
cli-anything-portdashboard --json system snapshot --force
```
