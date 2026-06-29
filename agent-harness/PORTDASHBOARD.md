# Port Dashboard — Software-Specific SOP

## Codebase Analysis (Phase 1)

### Backend Engine
Port Dashboard is a **FastAPI web service** (not a traditional GUI app). The backend is `app.py`, a single-file Python application using FastAPI + uvicorn + psutil. There is no separate rendering engine — all logic is self-contained.

### Data Model
- **Project configuration**: `projects.json` — array of project objects (id, name, cwd, command, port, description, sync_name)
- **Runtime PID tracking**: `running_pids.json` — maps project_id → {pid, managed, started_at}
- **Logs**: `logs/{project_id}.log` — per-project stdout/stderr capture

### API Endpoints → CLI Mapping

| API Endpoint | CLI Command | Description |
|---|---|---|
| `GET /api/projects` | `project list` | List all managed projects |
| `POST /api/projects` | `project add` | Register a new project |
| `PUT /api/projects/{id}` | `project update` | Update project config |
| `DELETE /api/projects/{id}` | `project remove` | Remove a project |
| `POST /api/projects/{id}/start` | `project start` | Start a project process |
| `POST /api/projects/{id}/stop` | `project stop` | Stop a running project |
| `GET /api/projects/{id}/logs` | `project logs` | Read project logs |
| `POST /api/projects/{id}/logs/clear` | `project logs-clear` | Clear project logs |
| `GET /api/system/ports` | `port scan` | Scan active TCP ports |
| `POST /api/system/ports/kill/{pid}` | `port kill` | Kill a process |
| `GET /api/system/stats` | `system stats` | CPU/memory stats |
| `GET /api/dashboard/snapshot` | `system snapshot` | Full dashboard snapshot |

### Key Observations
- The dashboard must be running for the CLI to work (it talks to the FastAPI API via HTTP)
- All state is persisted server-side (projects.json, running_pids.json)
- Process management uses `taskkill /T` on Windows for full process tree termination
- Port scanning uses psutil with netstat fallback

## CLI Architecture (Phase 2)

### Command Groups
1. **project** — Full project lifecycle management
2. **port** — Port scanning and process termination
3. **system** — System monitoring and full snapshots

### Interaction Model
- **Subcommand CLI** for scripting and one-shot operations
- **REPL** as default mode for interactive sessions
- **`--json`** flag for agent consumption

### State Model
State is managed entirely by the running dashboard service. The CLI is stateless — each command is a fresh HTTP request. No local session files needed.

### No Rendering/Export
Unlike creative software (Blender, GIMP), Port Dashboard has no rendering pipeline. All operations are data management (CRUD on projects) and process control. No preview or export features needed.
