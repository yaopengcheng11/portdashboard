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


class TestSlug:
    @pytest.mark.parametrize("raw,expected", [
        ("My Cool App", "my-cool-app"),
        ("@scope/pkg", "scope-pkg"),
        ("中文项目", "p-project"),
    ])
    def test_slugify_matches_id_rules(self, raw, expected):
        assert discovery.slugify_project_id(raw) == expected
