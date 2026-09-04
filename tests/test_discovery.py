"""discovery 模块单测 —— 用 tmp_path 构造假项目树，不依赖真实仓库。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discovery  # noqa: E402


def _make_node_project(root, name="web", *, script="vite", port=None, env_port=None,
                       config=None, dev=True):
    d = root / name
    d.mkdir(parents=True)
    scripts = {}
    if dev:
        scripts["dev"] = script
    scripts.setdefault("build", "vite build")
    pkg = {"name": name, "scripts": scripts}
    (d / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    if config:
        (d / f"vite.config.{config}").write_text(
            f"export default {{ server: {{ port: {port} }} }}", encoding="utf-8")
    if env_port:
        (d / ".env").write_text(f"PORT={env_port}\n", encoding="utf-8")
    return d


class TestDiscoverNode:
    def test_vite_project_default_port(self, tmp_path):
        _make_node_project(tmp_path, "my-web", script="vite", config="ts")
        out = discovery.discover_projects(str(tmp_path))
        assert len(out) == 1
        c = out[0]
        assert c["kind"] in ("vite", "node")
        assert c["port"] == 5173
        assert c["command"] == "npm run dev"
        assert c["id_hint"] == "my-web"

    def test_env_port_beats_config(self, tmp_path):
        _make_node_project(tmp_path, "a", config="js", port=5173, env_port=4400)
        (tmp_path / "a" / "vite.config.js").write_text("port: 1234", encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert out[0]["port"] == 4400

    def test_config_port_detected(self, tmp_path):
        _make_node_project(tmp_path, "b", config="js")
        (tmp_path / "b" / "vite.config.js").write_text("server: { port: 4173 }", encoding="utf-8")
        assert discovery.discover_projects(str(tmp_path))[0]["port"] == 4173

    def test_next_script_gets_3000(self, tmp_path):
        d = tmp_path / "nexty"
        d.mkdir()
        (d / "package.json").write_text(
            json.dumps({"name": "nexty", "scripts": {"dev": "next dev"}}), encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert out[0]["port"] == 3000
        assert out[0]["port_source"] == "next default"

    def test_library_without_dev_start_is_skipped(self, tmp_path):
        d = tmp_path / "lib-only"
        d.mkdir()
        (d / "package.json").write_text(
            json.dumps({"name": "lib-only", "scripts": {"test": "jest"}}), encoding="utf-8")
        assert discovery.discover_projects(str(tmp_path)) == []

    def test_start_script_fallback(self, tmp_path):
        d = tmp_path / "starter"
        d.mkdir()
        (d / "package.json").write_text(
            json.dumps({"name": "starter", "scripts": {"start": "node server.js"}}), encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert out[0]["command"] == "npm start"
        assert out[0]["port"] is None  # 无法推断时留给用户填


class TestDiscoverPython:
    def test_fastapi_entry(self, tmp_path):
        d = tmp_path / "pyapi"
        d.mkdir()
        (d / "app.py").write_text("pass", encoding="utf-8")
        (d / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert len(out) == 1
        assert out[0]["command"] == "python app.py"
        assert out[0]["port"] == 8000

    def test_plain_python_without_web_dep_skipped(self, tmp_path):
        d = tmp_path / "script"
        d.mkdir()
        (d / "main.py").write_text("print(1)", encoding="utf-8")
        (d / "requirements.txt").write_text("requests\n", encoding="utf-8")
        assert discovery.discover_projects(str(tmp_path)) == []

    def test_env_port_for_python(self, tmp_path):
        d = tmp_path / "pyapi2"
        d.mkdir()
        (d / "main.py").write_text("pass", encoding="utf-8")
        (d / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=['fastapi']\n", encoding="utf-8")
        (d / ".env").write_text("PORT=9000\n", encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert out[0]["port"] == 9000
        assert out[0]["command"] == "python main.py"


class TestScanBehaviour:
    def test_skips_node_modules_and_hidden(self, tmp_path):
        _make_node_project(tmp_path, "real")
        _make_node_project(tmp_path / "node_modules", "junk")
        _make_node_project(tmp_path / ".hidden", "junk2")
        out = discovery.discover_projects(str(tmp_path))
        assert [c["name"] for c in out] == ["real"]

    def test_depth_limit(self, tmp_path):
        deep = tmp_path / "l1" / "l2" / "l3"
        _make_node_project(deep, "too-deep")
        _make_node_project(tmp_path / "l1", "ok")
        # max_depth=1 只看根的直接子目录；ok 在孙层，需要 max_depth=2
        assert discovery.discover_projects(str(tmp_path), max_depth=1) == []
        out = discovery.discover_projects(str(tmp_path), max_depth=2)
        assert sorted(c["name"] for c in out) == ["ok"]

    def test_project_root_not_reentered(self, tmp_path):
        proj = _make_node_project(tmp_path, "outer")
        _make_node_project(proj, "nested")
        out = discovery.discover_projects(str(tmp_path))
        assert [c["name"] for c in out] == ["outer"]

    def test_root_itself_is_a_project(self, tmp_path):
        _make_node_project(tmp_path, "root-is-project")  # 直接把 package.json 写进 tmp_path
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "rootproj", "scripts": {"dev": "vite"}}), encoding="utf-8")
        out = discovery.discover_projects(str(tmp_path))
        assert any(c["name"] == "rootproj" for c in out)


class TestDetectGroups:
    """detect_project_groups —— "要一起启动才能用"的组合检测。"""

    @staticmethod
    def _proj(tmp_path, name, *, port=None, env=None, config=None):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        if config:
            (d / "vite.config.ts").write_text(config, encoding="utf-8")
        if env:
            (d / ".env").write_text(env, encoding="utf-8")
        return {"id": name, "name": name, "cwd": str(d), "port": port}

    def test_port_ref_links_frontend_to_backend(self, tmp_path):
        api = self._proj(tmp_path, "shop-api", port=8789, env="PORT=8789\n")
        web = self._proj(tmp_path, "shop-web", port=5173,
                         config="proxy: { '/api': { target: 'http://localhost:8789' } }")
        groups = discovery.detect_project_groups([api, web])
        assert len(groups) == 1
        g = groups[0]
        assert g["reason"] == "port-ref"
        assert g["steps"] == ["shop-api", "shop-web"]      # 被依赖的在前
        assert g["name"] == "shop"

    def test_own_port_not_treated_as_dependency(self, tmp_path):
        solo = self._proj(tmp_path, "solo", port=3000,
                          env="API_URL=http://localhost:3000\n")
        assert discovery.detect_project_groups([solo]) == []

    def test_env_backend_port_var_is_dependency(self, tmp_path):
        api = self._proj(tmp_path, "core", port=8000)
        web = self._proj(tmp_path, "ui", port=3000, env="BACKEND_PORT=8000\n")
        groups = discovery.detect_project_groups([web, api])
        assert groups and groups[0]["steps"] == ["core", "ui"]

    def test_three_chain_topological_order(self, tmp_path):
        db = self._proj(tmp_path, "db", port=5432)
        api = self._proj(tmp_path, "api", port=8000,
                         env="DATABASE_URL=postgres://localhost:5432/x\n")
        web = self._proj(tmp_path, "web", port=5173,
                         config="proxy target http://localhost:8000")
        groups = discovery.detect_project_groups([web, api, db])
        assert len(groups) == 1
        assert groups[0]["steps"] == ["db", "api", "web"]

    def test_name_grouping_fallback(self, tmp_path):
        a = self._proj(tmp_path, "alpha-api", port=8001)
        b = self._proj(tmp_path, "alpha-web", port=5174)
        c = self._proj(tmp_path, "unrelated", port=6000)
        groups = discovery.detect_project_groups([a, b, c])
        assert len(groups) == 1
        assert groups[0]["name"] == "alpha"
        assert groups[0]["reason"] == "name"
        assert groups[0]["steps"] == ["alpha-api", "alpha-web"]   # 后端角色排前

    def test_ambiguous_port_never_creates_bogus_edge(self, tmp_path):
        """两个项目都吃 vite 默认 5173 时，指向 5173 的引用无法归因，不能乱连线。"""
        other = self._proj(tmp_path, "portal", port=5173)
        backend = self._proj(tmp_path, "core", port=8000)
        web = self._proj(tmp_path, "webapp", port=5173,
                         config="proxy target http://localhost:8000")
        lone = self._proj(tmp_path, "loner", port=9000,
                          config="fetch base http://localhost:5173")
        groups = discovery.detect_project_groups([other, backend, web, lone])
        # web→core 是真依赖；lone→5173 因歧义不归因（portal 与 webapp 都可能）
        assert len(groups) == 1
        assert groups[0]["steps"] == ["core", "webapp"]

    def test_unrelated_projects_stay_ungrouped(self, tmp_path):
        a = self._proj(tmp_path, "blog", port=3000)
        b = self._proj(tmp_path, "tools", port=5173)
        assert discovery.detect_project_groups([a, b]) == []


class TestSlug:
    @pytest.mark.parametrize("raw,expected", [
        ("My Cool App", "my-cool-app"),
        ("@scope/pkg", "scope-pkg"),
        ("中文项目", "p-project"),
    ])
    def test_slugify_matches_id_rules(self, raw, expected):
        assert discovery.slugify_project_id(raw) == expected
