"""Start MCPHub with its state in /data and authentication that the dashboard cannot turn off."""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

DATA = Path("/data")
PORT = "3000"
# The upstream image's entrypoint and command: it sets the npm registry and then starts MCPHub.
UPSTREAM = ["/usr/local/bin/entrypoint.sh", "node", "dist/index.js"]
OPTIONS = {"tool_call_guard": bool}
SESSION_SECRET = re.compile(r"[0-9a-f]{64}")
# MCPHub falls back to these routing values when its settings omit them. The wrapper writes them
# on every start: a dashboard change lasts only until the next restart.
# enableBearerAuth=false opens /mcp to anyone; skipAuth=true opens the dashboard as admin.
ENFORCED_ROUTING = {"enableBearerAuth": True, "skipAuth": False}


class SetupError(Exception):
    pass


def read_options(data):
    try:
        options = json.loads((data / "options.json").read_text())
    except (OSError, ValueError):
        options = None
    if not isinstance(options, dict) or set(options) - set(OPTIONS) or any(
        not isinstance(options[name], kind) for name, kind in OPTIONS.items() if name in options
    ):
        raise SetupError("Invalid app options. Set tool_call_guard to true or false.")
    return {"tool_call_guard": options.get("tool_call_guard", False)}


def write_private(path, text):
    """Replace path with text in one step, readable only by its owner."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def session_secret(data):
    """Return the key that signs dashboard logins, so a restart keeps users logged in.

    A missing or malformed key is replaced: that only ends existing dashboard sessions.
    """
    path = data / "jwt-secret"
    try:
        saved = path.read_text().strip()
    except FileNotFoundError:
        saved = None
    if saved is not None and SESSION_SECRET.fullmatch(saved):
        os.chmod(path, 0o600)
        return saved
    if saved is not None:
        print("Replaced the unreadable dashboard session key. Dashboard users must log in again.", file=sys.stderr)
    secret = secrets.token_hex(32)
    write_private(path, secret + "\n")
    return secret


def enforce_authentication(data):
    """Write the enforced routing values into MCPHub's settings, keeping everything else."""
    path = data / "mcp_settings.json"
    if not path.exists():
        settings = {"mcpServers": {}, "users": [], "systemConfig": {"routing": dict(ENFORCED_ROUTING)}}
        write_private(path, json.dumps(settings, indent=2) + "\n")
        return
    text = path.read_text()
    try:
        settings = json.loads(text)
    except ValueError:
        settings = None
    if not isinstance(settings, dict):
        raise SetupError("/data/mcp_settings.json is not a JSON object. Restore it from a backup.")
    system = settings.setdefault("systemConfig", {})
    routing = system.setdefault("routing", {}) if isinstance(system, dict) else None
    if not isinstance(routing, dict):
        raise SetupError("systemConfig.routing in /data/mcp_settings.json is not an object. Restore it from a backup.")
    if any(routing.get(name) is not value for name, value in ENFORCED_ROUTING.items()):
        routing.update(ENFORCED_ROUTING)
        write_private(path, json.dumps(settings, indent=2) + "\n")
    else:
        os.chmod(path, 0o600)


def environment(options, secret, data):
    variables = {name: value for name, value in os.environ.items() if name not in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")}
    variables.update({
        # Any other value than development makes MCPHub generate a random first admin password.
        "NODE_ENV": "production",
        "PORT": PORT,
        "MCPHUB_SETTING_PATH": str(data / "mcp_settings.json"),
        "JWT_SECRET": secret,
        # The app pins MCPHub's version, so the dashboard's update notice could not be acted on.
        "DISABLE_UPDATE_CHECK": "true",
        "TOOL_CALL_GUARD_ENABLED": "true" if options["tool_call_guard"] else "false",
    })
    return variables


def prepare(data):
    options = read_options(data)
    secret = session_secret(data)
    enforce_authentication(data)
    return environment(options, secret, data)


def main():
    # MCPHub's own files, such as its credential key next to the settings, are created private too.
    os.umask(0o077)
    try:
        variables = prepare(DATA)
    except SetupError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    os.chdir("/app")
    os.execve(UPSTREAM[0], UPSTREAM, variables)


if __name__ == "__main__":
    main()
