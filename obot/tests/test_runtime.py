import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None


APP = Path(__file__).resolve().parents[1]
ENTRYPOINT = APP / "run.sh"


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)

    def configure(self, options, environment=None):
        (self.data / "options.json").write_text(json.dumps(options))
        result = subprocess.run(
            [
                "bash", "-c",
                'source "$1"\nconfigure_obot "$2"\n'
                'jq -n \'env | with_entries(select(.key | '
                'startswith("OBOT_") or . == "DOCKER_HOST" or '
                '. == "SUPERVISOR_TOKEN" or . == "HASSIO_TOKEN"))\' > "$3"',
                "test", str(ENTRYPOINT), str(self.data), str(self.data / "environment.json"),
            ],
            env={**os.environ, **(environment or {})}, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout, "", "The wrapper must not log secrets.")
        variables = None
        if result.returncode == 0:
            variables = json.loads((self.data / "environment.json").read_text())
        return result, variables

    def test_origin_validation(self):
        invalid = [
            "", "obot.example", "ftp://obot.example", "//obot.example",
            "http://", "https://user:password@obot.example",
            "https://obot.example/", "https://obot.example/mcp",
            "https://obot.example?x=1", "https://obot.example#fragment",
            "https://obot.example:0", "https://obot.example:65536",
            "https://obot.example:abc", "https://obot.example:\n8180",
            "https://obot..example", "https://-obot.example",
            "https://[:::]", "https://[1:2:3]", " https://obot.example",
            "https://obot.example\n",
        ]
        for url in invalid:
            with self.subTest(url=url):
                result, _ = self.configure({"server_url": url})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("server_url must be", result.stderr)
                self.assertFalse((self.data / "bootstrap-token").exists())

        for url in [
            "http://obot.example:8180", "https://obot.example",
            "http://192.0.2.4:8180", "http://localhost:8180",
            "https://[2001:db8::1]:8180", "https://[::1]",
            "https://[1:2:3:4:5:6:7:8]",
        ]:
            with self.subTest(url=url):
                result, variables = self.configure({"server_url": url})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(variables["OBOT_SERVER_HOSTNAME"], url)

    def test_invalid_option_shapes_fail_before_secret_creation(self):
        for options in [
            {}, [], {"server_url": None}, {"server_url": 8180},
            {"server_url": "https://obot.example", "bootstrap_token": False},
            {"server_url": "https://obot.example", "bootstrap_token": "short"},
            {"server_url": "https://obot.example", "bootstrap_token": "line\nbreak"},
            {"server_url": "https://obot.example", "bootstrap_token": "trailing-newline\n"},
            {"server_url": "https://obot.example", "authentication": False},
        ]:
            with self.subTest(options=options):
                result, _ = self.configure(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.data / "encryption.yaml").exists())
                self.assertFalse((self.data / "bootstrap-token").exists())

    def test_authentication_and_hosted_agents_cannot_be_overridden(self):
        result, variables = self.configure(
            {"server_url": "https://obot.example"},
            {
                "OBOT_SERVER_ENABLE_AUTHENTICATION": "false",
                "OBOT_ENABLE_AGENTS": "true",
                "OBOT_SERVER_ENABLE_HOSTED_AGENTS": "true",
                "OBOT_HOSTED_AGENTS_BACKEND": "remote",
                "SUPERVISOR_TOKEN": "supervisor-secret",
                "HASSIO_TOKEN": "legacy-supervisor-secret",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(variables["OBOT_SERVER_ENABLE_AUTHENTICATION"], "true")
        self.assertEqual(variables["OBOT_ENABLE_AGENTS"], "false")
        self.assertEqual(variables["OBOT_SERVER_ENABLE_HOSTED_AGENTS"], "false")
        self.assertEqual(variables["OBOT_HOSTED_AGENTS_BACKEND"], "disabled")
        self.assertEqual(variables["DOCKER_HOST"], "unix:///run/docker.sock")
        self.assertNotIn("SUPERVISOR_TOKEN", variables)
        self.assertNotIn("HASSIO_TOKEN", variables)

    def test_token_and_encryption_key_survive_restart(self):
        options = {"server_url": "https://obot.example", "bootstrap_token": ""}
        first, variables = self.configure(options)
        self.assertEqual(first.returncode, 0, first.stderr)
        token = (self.data / "bootstrap-token").read_bytes()
        encryption = (self.data / "encryption.yaml").read_bytes()
        config = json.loads(encryption)
        key = config["resources"][0]["providers"][0]["aesgcm"]["keys"][0]["secret"]
        self.assertEqual(len(base64.b64decode(key, validate=True)), 32)
        self.assertEqual(variables["OBOT_BOOTSTRAP_TOKEN"], token.decode().strip())
        self.assertEqual(variables["OBOT_SERVER_ENCRYPTION_PROVIDER"], "custom")
        self.assertEqual(variables["OBOT_SERVER_ENCRYPTION_CONFIG_FILE"], str(self.data / "encryption.yaml"))
        self.assertEqual((self.data / "bootstrap-token").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.data / "encryption.yaml").stat().st_mode & 0o777, 0o600)
        second, repeated = self.configure(options)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.data / "bootstrap-token").read_bytes(), token)
        self.assertEqual((self.data / "encryption.yaml").read_bytes(), encryption)
        self.assertEqual(repeated["OBOT_BOOTSTRAP_TOKEN"], variables["OBOT_BOOTSTRAP_TOKEN"])

    def test_explicit_bootstrap_token_is_passed_without_logging(self):
        token = 'secret-"with-quotes-and-$shell-characters'
        result, variables = self.configure({"server_url": "https://obot.example", "bootstrap_token": token})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(variables["OBOT_BOOTSTRAP_TOKEN"], token)
        self.assertNotIn(token, result.stderr)
        self.assertFalse((self.data / "bootstrap-token").exists())

    def test_empty_persistent_secret_is_not_rotated(self):
        for filename in ["bootstrap-token", "encryption.yaml"]:
            with self.subTest(filename=filename):
                path = self.data / filename
                path.write_text("")
                result, _ = self.configure({"server_url": "https://obot.example"})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), "")
                path.unlink()

    def test_existing_database_without_encryption_key_fails_closed(self):
        (self.data / "postgresql").mkdir()
        (self.data / "postgresql" / "PG_VERSION").write_text("17\n")
        result, _ = self.configure({"server_url": "https://obot.example"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restore encryption.yaml from backup", result.stderr)
        self.assertFalse((self.data / "encryption.yaml").exists())
        self.assertFalse((self.data / "bootstrap-token").exists())

    def test_invalid_saved_token_is_not_replaced(self):
        for token in ["short", "token with spaces", "token\nwith\nnewlines"]:
            with self.subTest(token=token):
                (self.data / "bootstrap-token").write_text(token)
                result, _ = self.configure({"server_url": "https://obot.example"})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.data / "bootstrap-token").read_text(), token)
                self.assertFalse((self.data / "encryption.yaml").exists())

    def test_original_upstream_init_is_exec_target(self):
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; configure_obot() { :; }; exec() { printf "%s" "$*"; }; main', "test", str(ENTRYPOINT)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "/bin/run.sh")
        dockerfile = (APP / "Dockerfile").read_text()
        self.assertIn("FROM ghcr.io/obot-platform/obot:v0.26.3", dockerfile)
        self.assertNotIn("COPY run.sh /bin/run.sh", dockerfile)

    @unittest.skipIf(yaml is None, "Install PyYAML to validate the Home Assistant schema.")
    def test_home_assistant_configuration(self):
        config = yaml.safe_load((APP / "config.yaml").read_text())
        self.assertEqual(config["arch"], ["amd64"])
        self.assertEqual(config["version"], "0.26.3-1")
        self.assertEqual(config["schema"], {"server_url": "url", "bootstrap_token": "password"})
        self.assertEqual(set(config["options"]), set(config["schema"]))
        self.assertIsNone(config["options"]["server_url"])
        self.assertEqual(config["ports"], {"8080/tcp": 8180})
        self.assertTrue(config["docker_api"])
        self.assertFalse(config["init"])
        self.assertFalse(config["ingress"])
        self.assertEqual(config["backup"], "cold")
        self.assertNotIn("image", config)
        self.assertNotIn("host_network", config)
        self.assertNotIn("full_access", config)
        self.assertNotIn("map", config)


if __name__ == "__main__":
    unittest.main()
