import socket
import sys
from pathlib import Path

import psutil
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402
import port_parser  # noqa: E402


class _FakeAddr:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


class _FakeConn:
    def __init__(self, ip, port, status="LISTEN"):
        self.laddr = _FakeAddr(ip, port)
        self.status = status


class _FakeProc:
    def __init__(self, pid, name, conns=(), raises=None):
        self.info = {"pid": pid, "name": name}
        self._conns = list(conns)
        self._raises = raises

    def net_connections(self, kind="tcp"):
        if self._raises:
            raise self._raises
        return self._conns


class TestListeningPorts:
    def test_shape_and_fields(self):
        procs = [_FakeProc(101, "node", [_FakeConn("0.0.0.0", 3000)])]
        out = port_parser._listening_from_psutil_procs(procs)
        assert len(out) == 1
        assert out[0]["port"] == 3000
        assert out[0]["pid"] == 101
        assert out[0]["process"] == "node"
        assert out[0]["address"] == "0.0.0.0:3000"
        assert out[0]["status"] == "listening"

    def test_ipv6_is_bracketed(self):
        """否则 ::1 + 端口会拼成有歧义的 ::1:4403。"""
        procs = [_FakeProc(1, "x", [_FakeConn("::1", 4403)])]
        assert port_parser._listening_from_psutil_procs(procs)[0]["address"] == "[::1]:4403"

    def test_dedupes_by_port_first_wins(self):
        procs = [
            _FakeProc(1, "first", [_FakeConn("0.0.0.0", 8080)]),
            _FakeProc(2, "second", [_FakeConn("::", 8080)]),
        ]
        out = port_parser._listening_from_psutil_procs(procs)
        assert len(out) == 1
        assert out[0]["process"] == "first"

    def test_skips_non_listening(self):
        procs = [_FakeProc(1, "x", [_FakeConn("0.0.0.0", 9000, status="ESTABLISHED")])]
        assert port_parser._listening_from_psutil_procs(procs) == []

    def test_access_denied_process_is_skipped(self):
        """非当前用户拥有的进程会拒绝，属正常，不能因此中断整轮枚举。"""
        procs = [
            _FakeProc(1, "denied", raises=psutil.AccessDenied(1)),
            _FakeProc(2, "ok", [_FakeConn("127.0.0.1", 5555)]),
        ]
        out = port_parser._listening_from_psutil_procs(procs)
        assert [p["port"] for p in out] == [5555]

    def test_finds_a_real_listening_socket(self):
        """真机烟雾测试。

        旧的 macOS 路径无条件返回空列表（netstat -lnp 以 64 退出），
        这条断言正是能抓住那类回归的检查。
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]

            found = [p for p in port_parser.parse_listening_ports({}) if p["port"] == port]
            assert found, f"未在枚举结果里找到自己监听的端口 {port}"
            assert found[0]["pid"] == psutil.Process().pid


class TestParseCommand:
    def test_simple_command(self):
        argv, env = app.parse_command("npm run dev")
        assert argv == ["npm", "run", "dev"]
        assert env == {}

    def test_env_overrides(self):
        argv, env = app.parse_command("PORT=3000 NODE_ENV=dev node server.js")
        assert argv == ["node", "server.js"]
        assert env == {"PORT": "3000", "NODE_ENV": "dev"}

    def test_empty_command_rejected(self):
        with pytest.raises(HTTPException):
            app.parse_command("   ")

    def test_env_only_rejected(self):
        with pytest.raises(HTTPException):
            app.parse_command("PORT=3000")


class TestValidateProjectId:
    def test_valid_id(self):
        assert app.validate_project_id("my-project_1") == "my-project_1"

    @pytest.mark.parametrize("bad", ["a/b", "a\\b", "../etc", "  "])
    def test_invalid_ids(self, bad):
        with pytest.raises(HTTPException):
            app.validate_project_id(bad)


class TestNormalizePidRegistry:
    def test_legacy_int_format(self):
        out = app.normalize_pid_registry({"p1": 123})
        assert out == {"p1": {"pid": 123, "managed": True, "started_at": None}}

    def test_dict_format(self):
        out = app.normalize_pid_registry({"p1": {"pid": 5, "managed": False, "started_at": 99}})
        assert out["p1"] == {"pid": 5, "managed": False, "started_at": 99}

    def test_garbage_dropped(self):
        out = app.normalize_pid_registry({"p1": "oops", "p2": {"no_pid": 1}})
        assert out == {}


class TestCategorizeProcess:
    def test_system_process(self):
        assert app.categorize_process("launchd", []) == "system"
        assert app.categorize_process("svchost.exe", []) == "system"

    def test_network_process(self):
        assert app.categorize_process("clash", []) == "network"

    def test_creative_process(self):
        assert app.categorize_process("blender", []) == "creative"

    def test_user_process_default(self):
        assert app.categorize_process("node", []) == "user"


class TestCoercePreferences:
    def test_defaults_on_garbage(self):
        assert app._coerce_preferences("not a dict") == app.DEFAULT_PREFERENCES

    def test_invalid_values_dropped(self):
        out = app._coerce_preferences({"theme": "nope", "refresh_interval": 7, "port": 99999})
        assert out == app.DEFAULT_PREFERENCES

    def test_valid_values_kept(self):
        out = app._coerce_preferences({"theme": "midnight", "refresh_interval": 10, "port": 8080, "auto_refresh": False})
        assert out["theme"] == "midnight"
        assert out["refresh_interval"] == 10
        assert out["port"] == 8080
        assert out["auto_refresh"] is False


class TestIsSystemPort:
    def test_known_system_port(self):
        assert app.is_system_port(3306)

    def test_user_port(self):
        assert not app.is_system_port(3000)
