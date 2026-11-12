from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError:
    yaml = None

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("startup", APP / "run.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.settings = self.data / "mcp_settings.json"
        self.secret = self.data / "jwt-secret"
        self.write_options({"tool_call_guard": False})

    def write_options(self, options):
        (self.data / "options.json").write_text(json.dumps(options))

    def prepare(self):
        output = io.StringIO()
        with redirect_stdout(output):
            variables = startup.prepare(self.data)
        self.assertEqual(output.getvalue(), "", "The wrapper must not print secrets.")
        return variables

    def test_first_start_creates_private_state_with_authentication_on(self):
        variables = self.prepare()
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings["systemConfig"]["routing"], {"enableBearerAuth": True, "skipAuth": False})
        self.assertEqual(settings["mcpServers"], {})
        self.assertEqual(settings["users"], [])
        self.assertRegex(self.secret.read_text(), r"\A[0-9a-f]{64}\n\Z")
        for path in (self.settings, self.secret):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)
        self.assertEqual(variables["JWT_SECRET"], self.secret.read_text().strip())
        self.assertEqual(variables["MCPHUB_SETTING_PATH"], str(self.settings))
        self.assertEqual(variables["PORT"], "3000")
        self.assertEqual(variables["NODE_ENV"], "production")
        self.assertEqual(variables["DISABLE_UPDATE_CHECK"], "true")
        self.assertEqual(variables["TOOL_CALL_GUARD_ENABLED"], "false")
        self.assertEqual(sorted(path.name for path in self.data.iterdir()), ["jwt-secret", "mcp_settings.json", "options.json"])

    def test_restart_keeps_session_key_and_settings(self):
        first = self.prepare()
        settings, secret = self.settings.read_bytes(), self.secret.read_bytes()
        second = self.prepare()
        self.assertEqual(self.settings.read_bytes(), settings)
        self.assertEqual(self.secret.read_bytes(), secret)
        self.assertEqual(second["JWT_SECRET"], first["JWT_SECRET"])

    def test_disabled_authentication_is_restored_and_other_settings_kept(self):
        saved = {
            "mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "tools": {"fetch": {"enabled": False}}}},
            "users": [{"username": "admin", "password": "hash", "isAdmin": True}],
            "groups": [{"id": "g1", "name": "devbox", "servers": ["fetch"]}],
            "bearerKeys": [{"id": "k1", "name": "agents", "tokenHash": "abc", "enabled": True, "accessType": "groups", "allowedGroups": ["devbox"]}],
            "systemConfig": {
                "routing": {"enableBearerAuth": False, "skipAuth": True, "enableGlobalRoute": False, "bearerAuthHeaderName": "X-Key"},
                "toolPolicies": [{"id": "deny", "effect": "deny", "tool": "fetch"}],
            },
        }
        self.settings.write_text(json.dumps(saved))
        os.chmod(self.settings, 0o644)
        self.prepare()
        settings = json.loads(self.settings.read_text())
        expected = json.loads(json.dumps(saved))
        expected["systemConfig"]["routing"].update(enableBearerAuth=True, skipAuth=False)
        self.assertEqual(settings, expected)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)

    def test_routing_values_that_are_not_booleans_are_replaced(self):
        for routing in [{}, {"enableBearerAuth": "true", "skipAuth": 0}, {"enableBearerAuth": 1, "skipAuth": None}]:
            with self.subTest(routing=routing):
                self.settings.write_text(json.dumps({"mcpServers": {}, "systemConfig": {"routing": routing}}))
                self.prepare()
                saved = json.loads(self.settings.read_text())["systemConfig"]["routing"]
                self.assertIs(saved["enableBearerAuth"], True)
                self.assertIs(saved["skipAuth"], False)

    def test_settings_without_system_config_get_one(self):
        self.settings.write_text(json.dumps({"mcpServers": {"a": {"url": "http://a/mcp"}}}))
        self.prepare()
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["mcpServers"], {"a": {"url": "http://a/mcp"}})
        self.assertEqual(saved["systemConfig"], {"routing": {"enableBearerAuth": True, "skipAuth": False}})

    def test_unreadable_settings_fail_without_being_replaced(self):
        for text in ["{not json", "[]", '"text"', json.dumps({"systemConfig": []}), json.dumps({"systemConfig": {"routing": "off"}})]:
            with self.subTest(text=text):
                self.settings.write_text(text)
                with redirect_stderr(io.StringIO()), self.assertRaises(startup.SetupError) as raised:
                    self.prepare()
                self.assertIn("Restore it from a backup", str(raised.exception))
                self.assertEqual(self.settings.read_text(), text)

    def test_unreadable_session_key_is_replaced_with_a_notice(self):
        for text in ["", "short\n", "Z" * 64, "a" * 63, "a" * 65]:
            with self.subTest(text=text):
                self.secret.write_text(text)
                errors = io.StringIO()
                with redirect_stderr(errors):
                    variables = self.prepare()
                self.assertIn("log in again", errors.getvalue())
                self.assertRegex(variables["JWT_SECRET"], r"\A[0-9a-f]{64}\Z")
                self.assertEqual(self.secret.read_text().strip(), variables["JWT_SECRET"])
                self.assertEqual(self.secret.stat().st_mode & 0o777, 0o600)

    def test_invalid_options_fail_before_any_state_is_written(self):
        for options in [[], {"tool_call_guard": "yes"}, {"tool_call_guard": 1}, {"tool_call_guard": False, "admin_password": "x"}]:
            with self.subTest(options=options):
                self.write_options(options)
                with self.assertRaises(startup.SetupError):
                    self.prepare()
                self.assertFalse(self.settings.exists())
                self.assertFalse(self.secret.exists())
        (self.data / "options.json").write_text("{broken")
        with self.assertRaises(startup.SetupError):
            self.prepare()

    def test_tool_call_guard_option_reaches_mcphub(self):
        self.write_options({"tool_call_guard": True})
        self.assertEqual(self.prepare()["TOOL_CALL_GUARD_ENABLED"], "true")

    def test_supervisor_tokens_and_overrides_do_not_reach_mcphub(self):
        caller = {
            "SUPERVISOR_TOKEN": "supervisor-secret", "HASSIO_TOKEN": "legacy-secret",
            "NODE_ENV": "development", "PORT": "1", "JWT_SECRET": "weak",
            "MCPHUB_SETTING_PATH": "/tmp/elsewhere.json", "TOOL_CALL_GUARD_ENABLED": "true", "TZ": "Europe/Amsterdam",
        }
        with patch.dict(os.environ, caller):
            variables = self.prepare()
        self.assertNotIn("SUPERVISOR_TOKEN", variables)
        self.assertNotIn("HASSIO_TOKEN", variables)
        self.assertEqual(variables["NODE_ENV"], "production")
        self.assertEqual(variables["PORT"], "3000")
        self.assertNotEqual(variables["JWT_SECRET"], "weak")
        self.assertEqual(variables["MCPHUB_SETTING_PATH"], str(self.settings))
        self.assertEqual(variables["TOOL_CALL_GUARD_ENABLED"], "false")
        self.assertEqual(variables["TZ"], "Europe/Amsterdam")

    def test_main_starts_the_upstream_entrypoint_privately(self):
        calls = []
        with patch.object(startup, "DATA", self.data), \
                patch.object(startup.os, "umask", side_effect=lambda mask: calls.append(("umask", mask))), \
                patch.object(startup.os, "chdir", side_effect=lambda path: calls.append(("chdir", path))), \
                patch.object(startup.os, "execve", side_effect=lambda path, arguments, variables: calls.append(("execve", path, arguments))):
            startup.main()
        self.assertEqual(calls, [
            ("umask", 0o077),
            ("chdir", "/app"),
            ("execve", "/usr/local/bin/entrypoint.sh", ["/usr/local/bin/entrypoint.sh", "node", "dist/index.js"]),
        ])

    def test_main_exits_with_the_reason_on_setup_errors(self):
        self.write_options({"tool_call_guard": "yes"})
        errors = io.StringIO()
        with patch.object(startup, "DATA", self.data), patch.object(startup.os, "umask"), \
                patch.object(startup.os, "execve") as execve, redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            startup.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Invalid app options", errors.getvalue())
        execve.assert_not_called()


class PackagingTests(unittest.TestCase):
    def test_dockerfile_pins_the_upstream_image_and_wraps_its_entrypoint(self):
        dockerfile = (APP / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"(?m)^FROM samanhappy/mcphub:1\.2\.3@sha256:[0-9a-f]{64}$")
        self.assertIn('ENTRYPOINT ["python3", "/usr/local/lib/ha-mcphub/run.py"]', dockerfile)
        self.assertIn("COPY run.py /usr/local/lib/ha-mcphub/run.py", dockerfile)

    @unittest.skipIf(yaml is None, "Install PyYAML to validate the Home Assistant schema.")
    def test_home_assistant_configuration(self):
        config = yaml.safe_load((APP / "config.yaml").read_text())
        self.assertEqual(config["slug"], "mcphub")
        self.assertEqual(config["arch"], ["amd64"])
        self.assertEqual(config["options"], {"tool_call_guard": False})
        self.assertEqual(config["schema"], {"tool_call_guard": "bool"})
        self.assertEqual(config["ports"], {"3000/tcp": 8190})
        self.assertEqual(set(config["ports_description"]), set(config["ports"]))
        self.assertTrue(config["init"])
        self.assertFalse(config["ingress"])
        for key in ("image", "docker_api", "host_network", "full_access", "privileged", "map", "homeassistant_api", "hassio_api"):
            self.assertNotIn(key, config)

    @unittest.skipIf(yaml is None, "Install PyYAML to validate the Home Assistant schema.")
    def test_versions_agree(self):
        version = yaml.safe_load((APP / "config.yaml").read_text())["version"]
        upstream = re.search(r"mcphub:([0-9.]+)@", (APP / "Dockerfile").read_text()).group(1)
        self.assertTrue(version.startswith(upstream + "-"), version)
        self.assertIn(f'io.hass.version="{version}"', (APP / "Dockerfile").read_text())
        self.assertIn(f"## {version}\n", (APP / "CHANGELOG.md").read_text())


if __name__ == "__main__":
    unittest.main()
