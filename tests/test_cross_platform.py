"""跨平台公平性单测 —— Unix 路径要和 Windows 一样开箱能跑。

双栈探测用真实 socket 验证（在 Windows 上也能测 ::1 分支）；
python→python3 回退与平台化命令生成用 monkeypatch 模拟 Unix。
"""
import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402
import discovery  # noqa: E402
import http_probe  # noqa: E402

def _v6_bindable():
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::1", 0))
        s.close()
        return True
    except OSError:
        return False


_IPV6_OK = socket.has_ipv6 and _v6_bindable()


class _TinyServer(threading.Thread):
    """极简 TCP 服务器：可发 HTTP 响应，也可发垃圾字节（非 web 内容）。"""

    def __init__(self, family, addr, payload):
        super().__init__(daemon=True)
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(addr)
        self.port = self.sock.getsockname()[1]
        self.sock.listen(4)
        self.payload = payload

    def run(self):
        self.sock.settimeout(0.3)
        while True:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.recv(4096)
                conn.sendall(self.payload)
            except OSError:
                pass
            finally:
                conn.close()


class TestHttpProbeDualStack:
    def test_ipv4_http_detected(self):
        srv = _TinyServer(socket.AF_INET, ("127.0.0.1", 0),
                          b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>")
        srv.start()
        try:
            assert http_probe.check_http_port(srv.port) is True
        finally:
            srv.sock.close()

    @pytest.mark.skipif(not _IPV6_OK, reason="IPv6 不可用")
    def test_ipv6_only_http_detected(self):
        """macOS 上 vite/next 常只绑 ::1 —— 旧实现只探 v4，永远 False。"""
        srv = _TinyServer(socket.AF_INET6, ("::1", 0),
                          b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>")
        srv.start()
        try:
            assert http_probe.check_http_port(srv.port) is True
        finally:
            srv.sock.close()

    def test_raw_tcp_is_not_web(self):
        srv = _TinyServer(socket.AF_INET, ("127.0.0.1", 0), b"\x00\x01garbage-not-http")
        srv.start()
        try:
            assert http_probe.check_http_port(srv.port) is False
        finally:
            srv.sock.close()

    def test_closed_port_is_false(self):
        port = 59999
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]  # 未 listen，保证拒连
        assert http_probe.check_http_port(port) is False


class TestUnixPythonFallback:
    def test_missing_python_falls_back_to_python3(self, monkeypatch):
        """Unix 上配置写着 python 但系统只有 python3 时，静默回退。"""
        monkeypatch.setattr(app, "IS_WINDOWS", False)
        monkeypatch.setattr(app.shutil, "which",
                            lambda name: "/usr/bin/python3" if name == "python3" else None)
        assert app._resolve_executable(["python", "app.py"]) == ["/usr/bin/python3", "app.py"]

    def test_bare_python_used_when_present(self, monkeypatch):
        monkeypatch.setattr(app, "IS_WINDOWS", False)
        monkeypatch.setattr(app.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert app._resolve_executable(["python", "app.py"]) == ["/usr/bin/python", "app.py"]


class TestDiscoveryPlatformCommands:
    def test_python_command_uses_python3_on_unix(self, monkeypatch, tmp_path):
        d = tmp_path / "pyapi"
        d.mkdir()
        (d / "app.py").write_text("x", encoding="utf-8")
        (d / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        monkeypatch.setattr(sys, "platform", "darwin")
        out = discovery._python_candidate(str(d))
        assert out["command"].startswith("python3 ")

    def test_python_command_uses_python_on_windows(self, monkeypatch, tmp_path):
        d = tmp_path / "pyapi"
        d.mkdir()
        (d / "app.py").write_text("x", encoding="utf-8")
        (d / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        monkeypatch.setattr(sys, "platform", "win32")
        out = discovery._python_candidate(str(d))
        assert out["command"].startswith("python ")


class TestUnixProtectedDaemons:
    @pytest.mark.parametrize("name", [
        "WindowServer", "securityd", "mdnsresponder", "opendirectoryd",
        "sshd", "systemd-resolved", "dbus-daemon", "cron",
    ])
    def test_core_daemons_classified_system(self, name):
        assert app.categorize_process(name) == "system"

    @pytest.mark.parametrize("name", ["WindowServer", "sshd", "securityd"])
    def test_core_daemons_refused_by_unix_guard(self, name, monkeypatch):
        """terminate_managed_pid 在 Unix 上必须拒杀这些守护。"""
        class FakeProc:
            def name(self):
                return name

        monkeypatch.setattr(app, "IS_WINDOWS", False)
        monkeypatch.setattr(app.psutil, "Process", lambda pid: FakeProc())
        assert app.terminate_managed_pid(12345) is False
