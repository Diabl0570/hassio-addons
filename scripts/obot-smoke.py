#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


ORIGIN = "http://127.0.0.1:8180"


def docker(*arguments, check=True):
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=check,
    ).stdout.strip()


def request(path, *, token=None, body=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    call = Request(
        ORIGIN + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        response = urlopen(call, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def wait_for_health(container):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if docker("inspect", "--format", "{{.State.Running}}", container) != "true":
            raise RuntimeError("Obot exited before becoming healthy.")
        try:
            if request("/api/healthz")[0] == 200:
                return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    raise RuntimeError("Obot did not become healthy within 180 seconds.")


def assert_authenticated_gateway(token):
    status, _, _ = request("/api/vmcps")
    if status != 401:
        raise RuntimeError(f"Unauthenticated API returned {status}, expected 401.")
    status, _, body = request("/api/vmcps", token=token)
    if status != 200 or not isinstance(json.loads(body).get("items"), list):
        raise RuntimeError("Bootstrap bearer token could not read the protected vMCP API.")
    status, headers, _ = request(
        "/mcp-connect/ha-obot-smoke-does-not-exist",
        body={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "ha-obot-smoke", "version": "1"},
            },
        },
    )
    if status != 401 or not headers.get("WWW-Authenticate"):
        raise RuntimeError("The MCP endpoint did not enforce bearer authentication.")


def persisted_files(container, directory):
    files = {}
    for name in ("bootstrap-token", "encryption.yaml"):
        destination = directory / name
        docker("cp", f"{container}:/data/{name}", str(destination))
        files[name] = destination.read_bytes()
    return files


def database(container, sql):
    return docker(
        "exec", container, "psql", "postgresql://obot:obot@localhost:5432/obot", "-Atc", sql,
    )


def main():
    parser = argparse.ArgumentParser(description="Run the Obot image on a disposable Docker daemon.")
    parser.add_argument("--image", default="ha-obot:test")
    image = parser.parse_args().image
    identifier = uuid.uuid4().hex[:12]
    container = f"ha-obot-smoke-{identifier}"
    volume = f"ha-obot-smoke-{identifier}"
    docker("volume", "create", volume)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            options = directory / "options.json"
            options.write_text(json.dumps({"server_url": ORIGIN, "bootstrap_token": ""}))
            docker(
                "create", "--name", container,
                "--mount", f"type=volume,src={volume},dst=/data",
                "--mount", "type=bind,src=/var/run/docker.sock,dst=/run/docker.sock",
                "--publish", "127.0.0.1:8180:8080", image,
            )
            docker("cp", str(options), f"{container}:/data/options.json")
            docker("start", container)
            wait_for_health(container)
            first = persisted_files(container, directory)
            token = first["bootstrap-token"].decode().strip()
            assert_authenticated_gateway(token)
            database(container, "CREATE TABLE ha_obot_smoke (value text); INSERT INTO ha_obot_smoke VALUES ('survived');")
            docker("restart", "--timeout", "30", container)
            wait_for_health(container)
            if persisted_files(container, directory) != first:
                raise RuntimeError("Restart changed the bootstrap token or encryption configuration.")
            if database(container, "SELECT value FROM ha_obot_smoke;") != "survived":
                raise RuntimeError("Bundled PostgreSQL data did not survive restart.")
            assert_authenticated_gateway(token)
            print("HTTP health, API/MCP authentication, and database/token/key restart persistence passed.")
    finally:
        docker("rm", "--force", container, check=False)
        docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
