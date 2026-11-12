#!/usr/bin/env python3
"""Run the MCPHub app image on a disposable Docker volume and check what an agent relies on."""
import argparse
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

# fetch is the only stdio server in the upstream image, so the check needs no package download.
FETCH = {"command": "uvx", "args": ["mcp-server-fetch"]}


def docker(*arguments, check=True):
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check).stdout


class DockerApp:
    """The app container as Home Assistant runs it: Docker's init, /data volume, mapped port."""

    origin = "http://127.0.0.1:8190"

    def __init__(self, image):
        identifier = uuid.uuid4().hex[:12]
        self.image = image
        self.container = f"ha-mcphub-smoke-{identifier}"
        self.volume = f"ha-mcphub-smoke-{identifier}"

    def start(self, options):
        docker("volume", "create", self.volume)
        docker(
            "create", "--init", "--name", self.container,
            "--mount", f"type=volume,src={self.volume},dst=/data",
            "--publish", "127.0.0.1:8190:3000", self.image,
        )
        self.write("options.json", json.dumps(options))
        docker("start", self.container)

    def running(self):
        return docker("inspect", "--format", "{{.State.Running}}", self.container).strip() == "true"

    def restart(self, while_stopped):
        docker("stop", "--timeout", "30", self.container)
        while_stopped()
        docker("start", self.container)

    def logs(self):
        result = subprocess.run(["docker", "logs", self.container], capture_output=True, text=True, check=True)
        return result.stdout + result.stderr

    def read(self, name):
        return docker("exec", self.container, "cat", f"/data/{name}")

    def mode(self, name):
        return docker("exec", self.container, "stat", "-c", "%a", f"/data/{name}").strip()

    def write(self, name, text):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / name
            source.write_text(text)
            docker("cp", str(source), f"{self.container}:/data/{name}")

    def remove(self):
        docker("rm", "--force", self.container, check=False)
        docker("volume", "rm", self.volume, check=False)


class Checks:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, body=None, headers=None):
        headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
        if body is not None:
            headers["Content-Type"] = "application/json"
        call = Request(
            self.app.origin + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = urlopen(call, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode()

    def wait_for(self, condition, what, seconds=180):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self.app.running():
                raise RuntimeError(f"MCPHub exited while waiting for {what}.\n{self.app.logs()[-4000:]}")
            try:
                if condition():
                    return
            except (URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
                pass
            time.sleep(2)
        raise RuntimeError(f"Timed out after {seconds} seconds waiting for {what}.")

    def health(self):
        status, _, body = self.request("GET", "/health")
        return json.loads(body) if status == 200 else None

    def login(self, password):
        status, _, body = self.request("POST", "/api/auth/login", {"username": "admin", "password": password})
        if status != 200:
            raise RuntimeError(f"Admin login returned {status}.")
        return {"x-auth-token": json.loads(body)["token"]}

    def mcp_tools(self, key):
        headers = {"Authorization": "Bearer " + key}
        status, response, _ = self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "ha-mcphub-smoke", "version": "1"}},
        }, headers)
        if status != 200:
            raise RuntimeError(f"MCP initialize with a bearer key returned {status}.")
        if "mcp-session-id" in response:
            headers["mcp-session-id"] = response["mcp-session-id"]
        self.request("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
        status, _, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)
        if status != 200:
            raise RuntimeError(f"MCP tools/list returned {status}.")
        return set(re.findall(r'"name":"([^"]+)"', body))

    def assert_mcp_requires_a_key(self):
        for headers in ({}, {"Authorization": "Bearer not-a-key"}):
            status, _, _ = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers)
            if status != 401:
                raise RuntimeError(f"/mcp without a valid key returned {status}, expected 401.")

    def assert_private_state(self):
        for name in ("mcp_settings.json", "jwt-secret"):
            if self.app.mode(name) != "600":
                raise RuntimeError(f"/data/{name} is readable by others.")

    def routing(self):
        return json.loads(self.app.read("mcp_settings.json"))["systemConfig"]["routing"]

    def run(self):
        self.app.start({"tool_call_guard": True})
        self.wait_for(lambda: self.health() is not None, "the health endpoint")
        match = re.search(r"Generated admin password: (\S+)", re.sub(r"\x1b\[[0-9;]*m", "", self.app.logs()))
        if not match:
            raise RuntimeError("MCPHub did not log a generated admin password on first start.")
        password = match.group(1)
        self.assert_mcp_requires_a_key()
        self.assert_private_state()

        dashboard = self.login(password)
        status, _, body = self.request("POST", "/api/auth/keys", {"name": "smoke", "enabled": True, "accessType": "all"}, dashboard)
        if status != 201:
            raise RuntimeError(f"Creating a bearer key returned {status}.")
        key = json.loads(body)["data"]["token"]
        status, _, _ = self.request("POST", "/api/servers", {"name": "fetch", "config": FETCH}, dashboard)
        if status != 200:
            raise RuntimeError(f"Adding the stdio fetch server returned {status}.")
        self.wait_for(lambda: self.health()["servers"]["connected"] == 1, "the stdio fetch server")
        if "fetch-fetch" not in self.mcp_tools(key):
            raise RuntimeError("The stdio server's tool is missing from /mcp.")

        # Turn authentication off the way a dashboard change would, while MCPHub cannot rewrite the
        # file. The start must turn it back on.
        settings = json.loads(self.app.read("mcp_settings.json"))
        settings["systemConfig"]["routing"].update(enableBearerAuth=False, skipAuth=True)
        secret = self.app.read("jwt-secret")
        self.app.restart(lambda: self.app.write("mcp_settings.json", json.dumps(settings)))
        self.wait_for(lambda: self.health()["servers"]["connected"] == 1, "the restarted app and its stdio server")

        if self.routing().get("enableBearerAuth") is not True or self.routing().get("skipAuth") is not False:
            raise RuntimeError("The restart did not restore authentication in the settings.")
        if self.app.read("jwt-secret") != secret:
            raise RuntimeError("The restart changed the dashboard session key.")
        self.assert_mcp_requires_a_key()
        self.assert_private_state()
        status, _, _ = self.request("GET", "/api/auth/keys", headers=dashboard)
        if status != 200:
            raise RuntimeError(f"A dashboard login from before the restart returned {status}.")
        self.login(password)
        if "fetch-fetch" not in self.mcp_tools(key):
            raise RuntimeError("The bearer key or the stdio server did not survive the restart.")
        if "Generated admin password" in re.sub(r"\x1b\[[0-9;]*m", "", self.app.logs()).split(password, 1)[1]:
            raise RuntimeError("MCPHub generated a second admin password after the restart.")
        print("Health, MCP bearer authentication, stdio tools, private state, and restart persistence passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="ha-mcphub:test")
    app = DockerApp(parser.parse_args().image)
    try:
        Checks(app).run()
    finally:
        app.remove()


if __name__ == "__main__":
    main()
