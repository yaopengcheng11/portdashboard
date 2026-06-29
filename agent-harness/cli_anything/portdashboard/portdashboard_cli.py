"""CLI-Anything Port Dashboard - main CLI entry point.

Usage:
    cli-anything-portdashboard [--json] [command]
    cli-anything-portdashboard              # enters REPL mode

Command groups:
    project   - manage projects (list, add, update, remove, start, stop, status, logs)
    port      - scan ports and kill processes (scan, kill)
    system    - system stats and full snapshot (stats, snapshot)
"""

import io
import json
import os
import sys
import unicodedata
import webbrowser

import click

from cli_anything.portdashboard import __version__
from cli_anything.portdashboard.core.project import (
    list_projects,
    get_project,
    create_project,
    update_project,
    delete_project,
    start_project,
    stop_project,
    get_logs,
    clear_logs,
)
from cli_anything.portdashboard.core.port import scan_ports, kill_process
from cli_anything.portdashboard.core.system import get_stats, get_snapshot

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr.encoding != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


import re

def _display_width(s):
    """Calculate display width, stripping ANSI escape codes."""
    s = re.sub(r'\033\[[0-9;]*m', '', str(s))
    width = 0
    for c in s:
        eaw = unicodedata.east_asian_width(c)
        if eaw in ("F", "W", "A"):
            width += 2
        else:
            width += 1
    return width


def _pad(s, width):
    """Pad string to target display width (ANSI-safe)."""
    s = str(s)
    actual = _display_width(s)
    return s + " " * max(0, width - actual)


def _truncate(s, max_width):
    """Truncate string to max display width."""
    s = str(s)
    if _display_width(s) <= max_width:
        return s
    result = ""
    w = 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 1
        if w + cw > max_width - 1:
            result += "…"
            break
        result += c
        w += cw
    return result


STATUS_COLORS = {
    "running": "green",
    "stopped": "red",
    "external": "yellow",
}


def _status_badge(status):
    color = STATUS_COLORS.get(status, "white")
    return click.style(status, fg=color, bold=True)


def _print_projects_table(projects):
    if not projects:
        click.echo(click.style("\n  No projects configured.", dim=True))
        click.echo(f"  Add one: {click.style('cli-anything-portdashboard project add --help', fg='cyan')}\n")
        return

    click.echo()
    for p in projects:
        status = str(p.get("status", ""))
        pid = p.get("pid")
        pid_str = str(pid) if pid else "-"

        click.echo(f"  {click.style(str(p.get('name', '')), bold=True, fg='cyan')}  [{_status_badge(status)}]")
        click.echo(f"    ID:      {p.get('id', '')}")
        click.echo(f"    Port:    {p.get('port', '')}")
        click.echo(f"    Command: {p.get('command', '')}")
        click.echo(f"    Dir:     {p.get('cwd', '')}")
        if pid:
            click.echo(f"    PID:     {pid}")
        click.echo()

    running = sum(1 for p in projects if p.get("status") == "running")
    total = len(projects)
    click.echo(f"  {click.style(str(total), bold=True)} project(s)  |  {click.style(str(running), fg='green', bold=True)} running  |  {total - running} stopped")
    click.echo()


def _print_ports_table(ports):
    if not ports:
        click.echo(click.style("\n  No active listening ports.\n", dim=True))
        return

    click.echo()

    user_ports = [p for p in ports if p["port"] >= 1024]
    system_ports = [p for p in ports if p["port"] < 1024]

    def _print_port_group(title, group):
        if not group:
            return
        click.echo(f"  {click.style(title, bold=True, fg='yellow')} ({len(group)})")
        for p in group:
            pid = p.get("pid") or "-"
            line = f"    {str(p.get('port', '')).rjust(6)}  {_truncate(str(p.get('address', '')), 22):<22}  {_truncate(str(p.get('process', '')), 20):<20}  PID {pid}"
            click.echo(line)
        click.echo()

    if user_ports:
        _print_port_group("User Ports (>= 1024)", user_ports)
    if system_ports:
        _print_port_group("System Ports (< 1024)", system_ports)

    click.echo(f"  Total: {click.style(str(len(ports)), bold=True)} port(s) listening")
    click.echo()


def _print_stats(stats):
    click.echo()
    cpu = stats.get("cpu_percent", 0)
    mem = stats.get("memory", {})
    mem_pct = mem.get("percent", 0)
    mem_used = mem.get("used_gb", 0)
    mem_total = mem.get("total_gb", 0)

    bar_width = 30

    def _bar(pct):
        filled = int(bar_width * pct / 100)
        color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
        bar = click.style("█" * filled, fg=color)
        bar += click.style("░" * (bar_width - filled), dim=True)
        return bar

    click.echo(f"  CPU     {_bar(cpu)}  {click.style(f'{cpu:.1f}%', bold=True)}")
    click.echo(f"  Memory  {_bar(mem_pct)}  {click.style(f'{mem_pct:.1f}%', bold=True)} ({mem_used:.1f} / {mem_total:.1f} GB)")
    click.echo()
    click.echo(f"  IP: {stats.get('ip_address', '?')}  |  Uptime: {stats.get('uptime', '?')}  |  OS: {stats.get('os', '?')}")
    click.echo()


def _print_project_detail(project):
    click.echo()
    status = project.get("status", "unknown")
    click.echo(f"  {click.style(project.get('name', '?'), bold=True, fg='cyan')}  [{_status_badge(status)}]")
    click.echo(f"  {_pad('ID:', 14)} {project.get('id', '')}")
    click.echo(f"  {_pad('Port:', 14)} {project.get('port', '')}")
    click.echo(f"  {_pad('Command:', 14)} {project.get('command', '')}")
    click.echo(f"  {_pad('Directory:', 14)} {project.get('cwd', '')}")

    pid = project.get("pid")
    if pid:
        click.echo(f"  {_pad('PID:', 14)} {pid}")

    owner = project.get("owner")
    if owner and owner != "Unknown":
        click.echo(f"  {_pad('Owner:', 14)} {owner}")

    desc = project.get("description")
    if desc:
        click.echo(f"  {_pad('Description:', 14)} {desc}")

    managed = project.get("managed", False)
    click.echo(f"  {_pad('Managed:', 14)} {'Yes' if managed else 'No'}")
    click.echo()


def _print_action_result(data):
    success = data.get("success", False)
    msg = data.get("message", "OK" if success else "Failed")

    if success:
        icon = click.style("✔", fg="green", bold=True)
    else:
        icon = click.style("✘", fg="red", bold=True)

    click.echo()
    click.echo(f"  {icon} {msg}")

    pid = data.get("pid")
    if pid:
        click.echo(f"    PID: {pid}")

    click.echo()


def _output(data, as_json):
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        _print_human(data)


def _print_human(data):
    """Generic fallback formatter. Commands override with specific printers."""
    if isinstance(data, list):
        if not data:
            click.echo(click.style("  (empty)", dim=True))
            return
        if data and isinstance(data[0], dict):
            keys = list(data[0].keys())
            widths = {k: max(_display_width(k), max((_display_width(_truncate(str(row.get(k, "")), 40)) for row in data), default=0)) for k in keys}
            header = "  ".join(_pad(k, widths[k]) for k in keys)
            click.echo(click.style(header, bold=True))
            click.echo("-" * _display_width(header))
            for row in data:
                click.echo("  ".join(_pad(_truncate(str(row.get(k, "")), 40), widths[k]) for k in keys))
    elif isinstance(data, dict):
        if "success" in data:
            _print_action_result(data)
        else:
            for k, v in data.items():
                if isinstance(v, dict):
                    click.echo(f"  {click.style(k, bold=True)}:")
                    for sk, sv in v.items():
                        click.echo(f"    {sk}: {sv}")
                elif isinstance(v, list):
                    click.echo(f"  {click.style(k, bold=True)}: [{len(v)} items]")
                else:
                    click.echo(f"  {k}: {v}")
    else:
        click.echo(str(data))


@click.group(invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.version_option(__version__, prog_name="cli-anything-portdashboard")
@click.pass_context
def cli(ctx, as_json):
    """CLI-Anything Port Dashboard - agent-native CLI for local service management."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = as_json
    if ctx.invoked_subcommand is None:
        _repl(ctx)


# ── project ──────────────────────────────────────────────────────────────

@cli.group()
@click.pass_context
def project(ctx):
    """Manage projects - add, list, start, stop, view logs."""
    pass


@project.command("list")
@click.pass_context
def project_list(ctx):
    """List all managed projects with their runtime status."""
    data = list_projects()
    if ctx.obj["json"]:
        _output(data, True)
    else:
        _print_projects_table(data)


@project.command("add")
@click.option("--id", "project_id", required=True, help="Unique project ID")
@click.option("--name", required=True, help="Display name")
@click.option("--cwd", required=True, help="Working directory")
@click.option("--command", required=True, help="Start command")
@click.option("--port", required=True, type=int, help="Target port")
@click.option("--description", default="", help="Description")
@click.option("--sync-name", is_flag=True, help="Auto-sync name from package.json/pyproject.toml")
@click.pass_context
def project_add(ctx, project_id, name, cwd, command, port, description, sync_name):
    """Add a new project to the dashboard."""
    data = create_project(project_id, name, cwd, command, port, description, sync_name)
    _output(data, ctx.obj["json"])


@project.command("update")
@click.argument("project_id")
@click.option("--name", required=True, help="Display name")
@click.option("--cwd", required=True, help="Working directory")
@click.option("--command", required=True, help="Start command")
@click.option("--port", required=True, type=int, help="Target port")
@click.option("--description", default="", help="Description")
@click.option("--sync-name", is_flag=True, help="Auto-sync name from package.json/pyproject.toml")
@click.pass_context
def project_update(ctx, project_id, name, cwd, command, port, description, sync_name):
    """Update an existing project's configuration."""
    data = update_project(project_id, name, cwd, command, port, description, sync_name)
    _output(data, ctx.obj["json"])


@project.command("remove")
@click.argument("project_id")
@click.pass_context
def project_remove(ctx, project_id):
    """Remove a project from the dashboard."""
    data = delete_project(project_id)
    _output(data, ctx.obj["json"])


@project.command("start")
@click.argument("project_id")
@click.pass_context
def project_start(ctx, project_id):
    """Start a project."""
    data = start_project(project_id)
    _output(data, ctx.obj["json"])


@project.command("stop")
@click.argument("project_id")
@click.pass_context
def project_stop(ctx, project_id):
    """Stop a running project."""
    data = stop_project(project_id)
    _output(data, ctx.obj["json"])


@project.command("status")
@click.argument("project_id")
@click.pass_context
def project_status(ctx, project_id):
    """Show detailed status for a project."""
    data = get_project(project_id)
    if data is None:
        click.echo(f"Error: project '{project_id}' not found", err=True)
        sys.exit(1)
    if ctx.obj["json"]:
        _output(data, True)
    else:
        _print_project_detail(data)


@project.command("logs")
@click.argument("project_id")
@click.option("--offset", default=0, type=int, help="Byte offset to start reading")
@click.option("--limit", default=65536, type=int, help="Max bytes to read")
@click.pass_context
def project_logs(ctx, project_id, offset, limit):
    """View project console logs."""
    data = get_logs(project_id, offset=offset, limit=limit)
    if ctx.obj["json"]:
        _output(data, True)
    else:
        logs = data.get("logs", "(no logs)")
        click.echo(logs)
        if data.get("truncated"):
            click.echo(click.style("\n... (output truncated, use --offset to read more)", dim=True))


@project.command("logs-clear")
@click.argument("project_id")
@click.pass_context
def project_logs_clear(ctx, project_id):
    """Clear project console logs."""
    data = clear_logs(project_id)
    _output(data, ctx.obj["json"])


# ── port ─────────────────────────────────────────────────────────────────

@cli.group()
@click.pass_context
def port(ctx):
    """Scan active ports and manage processes."""
    pass


@port.command("scan")
@click.pass_context
def port_scan(ctx):
    """Scan all active TCP listening ports."""
    data = scan_ports()
    if ctx.obj["json"]:
        _output(data, True)
    else:
        _print_ports_table(data)


@port.command("kill")
@click.argument("pid", type=int)
@click.pass_context
def port_kill(ctx, pid):
    """Kill a process by PID (use with caution)."""
    data = kill_process(pid)
    _output(data, ctx.obj["json"])


# ── system ───────────────────────────────────────────────────────────────

@cli.group()
@click.pass_context
def system(ctx):
    """System monitoring - CPU, memory, snapshot."""
    pass


@system.command("stats")
@click.pass_context
def system_stats(ctx):
    """Show system CPU and memory usage."""
    data = get_stats()
    if ctx.obj["json"]:
        _output(data, True)
    else:
        _print_stats(data)


@system.command("snapshot")
@click.option("--force", is_flag=True, help="Force refresh (bypass cache)")
@click.pass_context
def system_snapshot(ctx, force):
    """Full dashboard snapshot (stats + ports + projects)."""
    data = get_snapshot(force=force)
    if ctx.obj["json"]:
        _output(data, True)
    else:
        click.echo()
        click.echo(click.style("  System", bold=True, fg="cyan"))
        _print_stats(data.get("stats", {}))
        click.echo(click.style("  Ports", bold=True, fg="cyan"))
        _print_ports_table(data.get("system_ports", []))
        click.echo(click.style("  Projects", bold=True, fg="cyan"))
        _print_projects_table(data.get("projects", []))


# ── dashboard ────────────────────────────────────────────────────────────

@cli.command("open")
@click.pass_context
def dashboard_open(ctx):
    """Open the dashboard UI in a browser."""
    from cli_anything.portdashboard.core import get_base_url
    url = get_base_url()
    click.echo(f"Opening {url} ...")
    webbrowser.open(url)


# ── REPL ─────────────────────────────────────────────────────────────────

def _repl(ctx):
    as_json = ctx.obj["json"]

    try:
        from cli_anything.portdashboard.utils.repl_skin import ReplSkin
        skin = ReplSkin("portdashboard", version=__version__)
        skin.print_banner()
        pt_session = skin.create_prompt_session()
    except ImportError:
        skin = None
        pt_session = None
        click.echo(f"CLI-Anything Port Dashboard v{__version__}")
        click.echo("Type 'help' for commands, 'exit' to quit.\n")

    commands = {
        "project list":    "List all projects",
        "project add":     "Add a project (interactive)",
        "project start":   "Start a project: project start <id>",
        "project stop":    "Stop a project: project stop <id>",
        "project status":  "Show project status: project status <id>",
        "project remove":  "Remove a project: project remove <id>",
        "project logs":    "View logs: project logs <id>",
        "port scan":       "Scan active listening ports",
        "port kill":       "Kill process: port kill <pid>",
        "system stats":    "Show CPU/memory stats",
        "system snapshot": "Full dashboard snapshot",
        "open":            "Open dashboard in browser",
        "help":            "Show this help",
        "exit":            "Exit REPL",
    }

    while True:
        try:
            if pt_session and skin:
                line = skin.get_input(pt_session)
            else:
                line = input("portdashboard> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        if line in ("exit", "quit", "q"):
            break

        if line == "help":
            if skin:
                skin.help(commands)
            else:
                for cmd, desc in commands.items():
                    click.echo(f"  {cmd:<20s} {desc}")
            continue

        parts = line.split()
        cmd = parts[0]
        args = parts[1:]

        try:
            if cmd == "open":
                dashboard_open.callback(ctx)
            elif len(parts) >= 2 and parts[0] == "project":
                sub = parts[1]
                rest = parts[2:]
                _repl_project(sub, rest, as_json)
            elif len(parts) >= 2 and parts[0] == "port":
                sub = parts[1]
                rest = parts[2:]
                _repl_port(sub, rest, as_json)
            elif len(parts) >= 2 and parts[0] == "system":
                sub = parts[1]
                rest = parts[2:]
                _repl_system(sub, rest, as_json)
            else:
                click.echo(f"Unknown command: {line}")
                click.echo("Type 'help' for available commands.")
        except SystemExit:
            pass
        except Exception as e:
            click.echo(f"Error: {e}", err=True)

    if skin:
        skin.print_goodbye()
    else:
        click.echo("Goodbye!")


def _repl_project(sub, rest, as_json):
    if sub == "list":
        data = list_projects()
        _output(data, as_json)
    elif sub == "start" and rest:
        data = start_project(rest[0])
        _output(data, as_json)
    elif sub == "stop" and rest:
        data = stop_project(rest[0])
        _output(data, as_json)
    elif sub == "status" and rest:
        data = get_project(rest[0])
        if data:
            _output(data, as_json)
        else:
            click.echo(f"Project '{rest[0]}' not found")
    elif sub == "remove" and rest:
        data = delete_project(rest[0])
        _output(data, as_json)
    elif sub == "logs" and rest:
        data = get_logs(rest[0])
        if as_json:
            _output(data, True)
        else:
            click.echo(data.get("logs", "(no logs)"))
    elif sub == "logs-clear" and rest:
        data = clear_logs(rest[0])
        _output(data, as_json)
    elif sub == "add":
        click.echo("Use the CLI command to add projects:")
        click.echo("  cli-anything-portdashboard project add --id X --name Y --cwd Z --command C --port P")
    else:
        click.echo(f"Unknown project command: {sub}")


def _repl_port(sub, rest, as_json):
    if sub == "scan":
        data = scan_ports()
        _output(data, as_json)
    elif sub == "kill" and rest:
        try:
            pid = int(rest[0])
            data = kill_process(pid)
            _output(data, as_json)
        except ValueError:
            click.echo(f"Invalid PID: {rest[0]}")
    else:
        click.echo(f"Unknown port command: {sub}")


def _repl_system(sub, rest, as_json):
    if sub == "stats":
        data = get_stats()
        _output(data, as_json)
    elif sub == "snapshot":
        force = "--force" in rest
        data = get_snapshot(force=force)
        _output(data, as_json)
    else:
        click.echo(f"Unknown system command: {sub}")


if __name__ == "__main__":
    cli()
