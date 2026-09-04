"""discovery — 扫描目录，识别可托管的开发项目并推断启动命令与端口。

从 app.py 的托管语义出发回答一个问题："这个目录下还有哪些项目值得接管？"
识别两类项目根：
    * Node：package.json（dev/start script）
    * Python：pyproject.toml 或 requirements.txt + 常见入口文件（app/main/server.py）

端口推断优先级：.env(.local) 的 PORT > vite/next/nuxt 配置里的显式 port >
脚本里的 --port/-p 参数 > 框架默认值（vite 5173 / next·nuxt 3000 / web.py 8000）。
推断只是建议，UI 里可改，导入时仍走完整的 Project 校验。

Public surface:
    discover_projects(root, max_depth=2) -> List[dict]
    slugify_project_id(name) -> str
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Optional, Tuple

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", ".output", "coverage",
    "logs", "log", "target", "vendor", ".uishots", ".hermes", ".pytest_cache",
    "$RECYCLE.BIN", "system volume information",
}

_MAX_FILE_READ = 64 * 1024
_ENV_PORT_RE = re.compile(r"^\s*(?:PORT|VITE_PORT)\s*=\s*(\d{2,5})", re.MULTILINE)
_CONFIG_PORT_RE = re.compile(r"port['\"]?\s*[:=]\s*(\d{2,5})")
_FLAG_PORT_RE = re.compile(r"(?:--port|-p)\s+(\d{2,5})")
_PY_WEB_DEP_RE = re.compile(r"\b(fastapi|uvicorn|flask|django)\b", re.IGNORECASE)

_PY_ENTRIES = ("app.py", "main.py", "server.py")


def _read_text(path: str, limit: int = _MAX_FILE_READ) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def slugify_project_id(name: str) -> str:
    """目录名/包名 -> 合法项目 id（与 app._PROJECT_ID_RE 对齐）。"""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    if not slug or not re.match(r"^[A-Za-z0-9]", slug):
        slug = f"p-{slug or 'project'}"
    return slug[:64]


def _port_from_env_files(project_dir: str) -> Optional[int]:
    for env_name in (".env.local", ".env"):
        m = _ENV_PORT_RE.search(_read_text(os.path.join(project_dir, env_name), 4096))
        if m:
            return int(m.group(1))
    return None


def _framework_and_port(project_dir: str, package_json_text: str,
                        scripts_text: str) -> Tuple[str, Optional[int], str]:
    """返回 (framework, port, port_source)。package.json 文本用于框架识别。"""
    vite_cfg = next((f for f in os.listdir(project_dir)
                     if f.startswith("vite.config.")) if os.path.isdir(project_dir) else [], None)
    scripts_lower = scripts_text.lower()
    pkg_lower = package_json_text.lower()

    port = _port_from_env_files(project_dir)
    if port:
        return "node", port, ".env PORT"

    # 配置文件里的显式 port
    for cfg in ("vite.config.ts", "vite.config.js", "vite.config.mjs",
                "nuxt.config.ts", "nuxt.config.js", "next.config.js", "next.config.mjs",
                "webpack.config.js", "vue.config.js"):
        text = _read_text(os.path.join(project_dir, cfg), _MAX_FILE_READ)
        m = _CONFIG_PORT_RE.search(text)
        if m:
            return "node", int(m.group(1)), cfg

    # script 里的 --port / -p
    m = _FLAG_PORT_RE.search(scripts_text)
    if m:
        return "node", int(m.group(1)), "script flag"

    # 框架默认值
    if "next" in pkg_lower or "next dev" in scripts_lower:
        return "next", 3000, "next default"
    if "nuxt" in pkg_lower:
        return "nuxt", 3000, "nuxt default"
    if "vite" in pkg_lower or vite_cfg:
        return "vite", 5173, "vite default"
    return "node", None, ""


def _node_candidate(project_dir: str) -> Optional[dict]:
    pkg_path = os.path.join(project_dir, "package.json")
    try:
        with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
            pkg = json.load(f)
    except (OSError, ValueError):
        return None
    scripts = pkg.get("scripts") or {}
    if not isinstance(scripts, dict):
        scripts = {}

    if "dev" in scripts:
        command = "npm run dev"
    elif "start" in scripts:
        command = "npm start"
    else:
        return None  # 没有 dev/start 的包（纯库）不值得托管

    framework, port, port_source = _framework_and_port(project_dir, json.dumps(pkg),
                                                       json.dumps(scripts))
    name = (pkg.get("productName") or pkg.get("name") or "").strip() \
        or os.path.basename(project_dir)
    return {
        "cwd": project_dir,
        "name": name,
        "kind": framework,
        "command": command,
        "port": port,
        "port_source": port_source,
        "id_hint": slugify_project_id(pkg.get("name") or os.path.basename(project_dir)),
    }


def _python_candidate(project_dir: str) -> Optional[dict]:
    entry = next((f for f in _PY_ENTRIES if os.path.isfile(os.path.join(project_dir, f))), None)
    if not entry:
        return None

    dep_text = ""
    req = os.path.join(project_dir, "requirements.txt")
    pyproject = os.path.join(project_dir, "pyproject.toml")
    if os.path.isfile(req):
        dep_text = _read_text(req)
    elif os.path.isfile(pyproject):
        dep_text = _read_text(pyproject)
    if not _PY_WEB_DEP_RE.search(dep_text):
        return None  # 没有Web依赖的 python 目录（脚本/库）不猜

    port = _port_from_env_files(project_dir) or 8000
    # 现代 macOS 没有裸 python（只有 python3），Linux 发行版也普遍如此；
    # Windows 才叫 python。生成的命令必须开箱能跑。
    python_bin = "python" if sys.platform == "win32" else "python3"
    return {
        "cwd": project_dir,
        "name": os.path.basename(project_dir),
        "kind": "python",
        "command": f"{python_bin} {entry}",
        "port": port,
        "port_source": ".env PORT" if _port_from_env_files(project_dir) else "web.py default",
        "id_hint": slugify_project_id(os.path.basename(project_dir)),
    }


def _candidate_at(project_dir: str) -> Optional[dict]:
    if os.path.isfile(os.path.join(project_dir, "package.json")):
        return _node_candidate(project_dir)
    if os.path.isfile(os.path.join(project_dir, "pyproject.toml")) \
            or os.path.isfile(os.path.join(project_dir, "requirements.txt")):
        return _python_candidate(project_dir)
    return None


_LOCAL_URL_RE = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\]|::1):(\d{2,5})", re.IGNORECASE)
_OTHER_ENV_PORT_RE = re.compile(r"^\s*([A-Za-z0-9_]*?)PORT\s*=\s*(\d{2,5})", re.MULTILINE)
_GROUP_ROLE_SUFFIXES = ("frontend", "backend", "webui", "dashboard", "web", "front", "server", "client", "api", "ui", "app")

_DETECT_FILES = (
    "vite.config.ts", "vite.config.js", "vite.config.mjs",
    "next.config.js", "next.config.mjs",
    "nuxt.config.ts", "nuxt.config.js",
    "webpack.config.js", "vue.config.js",
    ".env.local", ".env", ".env.development",
)


def _referenced_ports(cwd: str, own_port) -> set:
    """项目配置/.env 里引用的**别的**服务端口（依赖信号）。

    localhost:PORT 形式的 URL（vite proxy target、next rewrite、API_URL…）
    以及 API_PORT=xxxx 这类非自身端口变量；自身 PORT / VITE_PORT 不算依赖。
    """
    refs = set()
    for fname in _DETECT_FILES:
        text = _read_text(os.path.join(cwd, fname))
        if not text:
            continue
        for m in _LOCAL_URL_RE.finditer(text):
            refs.add(int(m.group(1)))
        for m in _OTHER_ENV_PORT_RE.finditer(text):
            if m.group(1) not in ("", "VITE"):
                refs.add(int(m.group(2)))
    refs.discard(own_port)
    return refs


def _strip_role_suffix(name: str) -> str:
    """cg-resource-hub-api -> cg-resource-hub；@scope/web-ui -> scope 名保留去 ui。"""
    n = re.sub(r"^@[^/]+/", "", (name or "").strip().lower())
    n = re.sub(r"[^a-z0-9_-]", "-", n)
    changed = True
    while changed and n:
        changed = False
        for suf in _GROUP_ROLE_SUFFIXES:
            for sep in ("-", "_"):
                if n.endswith(sep + suf):
                    n = n[: -(len(suf) + 1)]
                    changed = True
    return n


def _order_component(members: List[dict], deps: dict) -> List[str]:
    """组内排序：被依赖的在前（Kahn），同层按端口，有环则兜底接尾。"""
    ids = [m["id"] for m in members]
    idset = set(ids)
    port_of = {m["id"]: (m.get("port") or 0) for m in members}
    indeg = {i: 0 for i in ids}
    dependents: dict = {i: [] for i in ids}
    for u in ids:
        for v in deps.get(u, ()):
            if v in idset:
                indeg[u] += 1
                dependents[v].append(u)
    ready = sorted([i for i in ids if indeg[i] == 0], key=lambda i: port_of[i])
    out = []
    while ready:
        node = ready.pop(0)
        out.append(node)
        for dep in dependents[node]:
            indeg[dep] -= 1
            if indeg[dep] == 0:
                ready.append(dep)
        ready.sort(key=lambda i: port_of[i])
    out += sorted([i for i in ids if i not in set(out)], key=lambda i: port_of[i])
    return out


def _group_name(members: List[dict], deps: dict) -> str:
    bases = {_strip_role_suffix(m.get("name") or "") for m in members}
    bases.discard("")
    if len(bases) == 1:
        return bases.pop()
    ref_count: dict = {}
    for targets in deps.values():
        for v in targets:
            ref_count[v] = ref_count.get(v, 0) + 1
    backend = max(members, key=lambda m: ref_count.get(m["id"], 0))
    return _strip_role_suffix(backend.get("name") or "") \
        or backend.get("name") or "scene"


def detect_project_groups(projects: List[dict]) -> List[dict]:
    """识别"要一起启动才能用"的项目组合。

    信号优先级：
      1. 端口引用 —— 项目配置/.env 里出现指向另一项目端口的 localhost URL
         （vite proxy target、API_URL 等），即"启动我也得先启动它"；
      2. 命名配套 —— 去掉 -api/-web/-server/-client 等角色后缀后同名的落单项目。

    入参每项: {id, name, cwd, port}；返回 [{"name", "steps"(依赖在前), "reason"}]，
    每个项目至多属于一组（端口引用组优先）。
    """
    items = [p for p in projects if p.get("id") and p.get("cwd")]
    # 端口 → 项目 归因表：多个项目声明同一端口（如都吃 vite 默认 5173）时
    # 该端口歧义，引用无法归因，直接弃用 —— 否则会产生假依赖边。
    by_port: dict = {}
    for p in items:
        port = p.get("port")
        if not port:
            continue
        if port in by_port:
            by_port[port] = None
        else:
            by_port[port] = p
    by_port = {k: v for k, v in by_port.items() if v is not None}
    deps: dict = {}
    for p in items:
        for rp in _referenced_ports(p["cwd"], p.get("port")):
            target = by_port.get(rp)
            if target and target["id"] != p["id"]:
                deps.setdefault(p["id"], set()).add(target["id"])

    # 并查集：依赖边当无向看，连通分量 = "一套"
    parent = {p["id"]: p["id"] for p in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, targets in deps.items():
        for v in targets:
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv

    components: dict = {}
    for p in items:
        components.setdefault(find(p["id"]), []).append(p)

    groups: List[dict] = []
    grouped = set()
    for members in components.values():
        if len(members) >= 2:
            ids = _order_component(members, deps)
            groups.append({"name": _group_name(members, deps),
                           "steps": ids, "reason": "port-ref"})
            grouped.update(ids)

    leftovers = [p for p in items if p["id"] not in grouped]
    by_base: dict = {}
    for p in leftovers:
        base = _strip_role_suffix(p.get("name") or "")
        if len(base) >= 3:
            by_base.setdefault(base, []).append(p)
    for base, members in by_base.items():
        if len(members) >= 2:
            members.sort(key=lambda p: (0 if (p.get("name") or "").lower().endswith(
                ("api", "server", "backend")) else 1, p.get("port") or 0))
            groups.append({"name": base,
                           "steps": [p["id"] for p in members], "reason": "name"})
    return groups


def discover_projects(root: str, max_depth: int = 2) -> List[dict]:
    """扫描 root（含 root 本身），返回可托管项目候选列表。

    深度限制：root 之下最多再钻 max_depth 层；识别为项目根的目录不再往下钻
    （monorepo 子包场景留待后续）。跳过 node_modules / .git / 构建产物等噪声目录。
    """
    root = os.path.abspath(root)
    candidates: List[dict] = []

    direct = _candidate_at(root)
    if direct:
        candidates.append(direct)

    def walk(dir_path: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(dir_path), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.startswith(".") or entry.name.lower() in SKIP_DIRS:
                continue
            candidate = _candidate_at(entry.path)
            if candidate:
                candidates.append(candidate)
            else:
                walk(entry.path, depth + 1)

    walk(root, 1)
    return candidates
