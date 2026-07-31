import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


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
