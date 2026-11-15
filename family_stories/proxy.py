"""A fixed-origin HTTPS proxy reachable only through Supervisor ingress."""

import base64
from dataclasses import dataclass
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import sys
from urllib.parse import urljoin, urlsplit

SUPERVISOR_IP = "172.30.32.2"
MAX_BODY = 25 * 1024 * 1024
REQUEST_HEADERS = {
    "accept", "accept-language", "accept-encoding", "range",
    "if-none-match", "if-modified-since", "content-type", "x-requested-with",
}
DROP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "set-cookie",
    "www-authenticate", "server", "date", "access-control-allow-origin",
    "access-control-allow-credentials", "access-control-allow-methods",
    "access-control-allow-headers",
}


@dataclass(frozen=True)
class Settings:
    hostname: str
    origin: str
    authorization: str

    @classmethod
    def from_options(cls, options):
        if not isinstance(options, dict):
            raise ValueError("App options must be an object")
        target = urlsplit(options.get("target_url", ""))
        if (target.scheme != "https" or not target.hostname
                or target.username is not None or target.password is not None
                or target.port not in (None, 443) or target.path not in ("", "/")
                or target.query or target.fragment
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", target.hostname)):
            raise ValueError("target_url must be a public HTTPS origin on port 443")
        try:
            ipaddress.ip_address(target.hostname)
        except ValueError:
            pass
        else:
            raise ValueError("target_url must use a public DNS hostname")
        username = options.get("username", "")
        password = options.get("password", "")
        if (not isinstance(username, str) or not isinstance(password, str)
                or not username or not password or ":" in username
                or any(ord(c) < 32 or ord(c) == 127 for c in username + password)):
            raise ValueError("A username and password are required")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return cls(target.hostname, f"https://{target.hostname}", f"Basic {token}")


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise OSError("The upstream DNS answer is not public")
        # Connect to the already validated address, retaining hostname verification.
        sock = socket.create_connection(addresses[0][4][:2], self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, settings, *, accepted_peer=SUPERVISOR_IP,
                 connection_factory=PublicHTTPSConnection):
        self.settings = settings
        self.accepted_peer = accepted_peer
        self.connection_factory = connection_factory
        super().__init__(address, ProxyHandler)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # Request URLs can contain the private ingress token.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def reject(self, status, message):
        body = json.dumps({"error": {"message": message}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self.forward()

    do_HEAD = do_GET
    do_POST = do_GET

    def do_OPTIONS(self):
        self.reject(403, "Cross-origin requests are not allowed")

    def forward(self):
        if self.client_address[0] != self.server.accepted_peer:
            return self.reject(403, "Use Home Assistant ingress")
        ingress = self.headers.get("X-Ingress-Path", "").rstrip("/")
        if not re.fullmatch(r"/api/hassio_ingress/[A-Za-z0-9_-]+", ingress):
            return self.reject(403, "Missing Home Assistant ingress path")
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            return self.reject(400, "Invalid request path")
        if not self.path.startswith("/") or self.path.startswith("//") or parsed.scheme or parsed.netloc:
            return self.reject(400, "Invalid request path")
        if self.command == "POST" and not self.valid_post_origin():
            return self.reject(403, "This request did not come from the story app")
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
            return self.reject(400, "Unsupported request framing")
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            return self.reject(400, "Invalid content length")
        if length < 0 or length > MAX_BODY:
            return self.reject(413, "Request body is too large")
        if self.command != "POST" and length:
            return self.reject(400, "Unexpected request body")
        body = self.rfile.read(length) if length else None
        if body is not None and len(body) != length:
            return self.reject(400, "Incomplete request body")
        headers = {k: v for k, v in self.headers.items() if k.lower() in REQUEST_HEADERS}
        headers["Authorization"] = self.server.settings.authorization
        headers["X-Ingress-Path"] = ingress
        if self.command == "POST":
            headers["Origin"] = self.server.settings.origin
        upstream = self.server.connection_factory(self.server.settings.hostname, timeout=90)
        started = False
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            if response.status in (401, 407):
                return self.reject(502, "Check the story server credentials in the app options")
            location = response.getheader("Location")
            if location:
                resolved = urlsplit(urljoin(self.server.settings.origin + self.path, location))
                if (resolved.scheme != "https" or resolved.hostname != self.server.settings.hostname
                        or resolved.port not in (None, 443)
                        or resolved.username is not None or resolved.password is not None):
                    return self.reject(502, "The story server returned an external redirect")
                location = ingress + (resolved.path or "/")
                if resolved.query:
                    location += "?" + resolved.query
                if resolved.fragment:
                    location += "#" + resolved.fragment
            self.send_response(response.status)
            blocked = DROP_RESPONSE_HEADERS | {h.strip().lower() for h in response.getheader("Connection", "").split(",")}
            for key, value in response.getheaders():
                if key.lower() not in blocked and key.lower() != "location":
                    self.send_header(key, value)
            if location:
                self.send_header("Location", location)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            started = True
            if self.command != "HEAD":
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
        except (OSError, ValueError, http.client.HTTPException):
            if not started:
                self.reject(502, "The story server is unavailable")
        finally:
            upstream.close()

    def valid_post_origin(self):
        try:
            origin = urlsplit(self.headers.get("Origin", ""))
        except ValueError:
            return False
        host = self.headers.get("Host", "").lower()
        forwarded_proto = self.headers.get("X-Forwarded-Proto")
        return (origin.scheme in ("http", "https") and origin.netloc.lower() == host
                and not origin.path and not origin.query and not origin.fragment
                and origin.username is None and origin.password is None
                and (forwarded_proto is None or forwarded_proto == origin.scheme)
                and self.headers.get("Sec-Fetch-Site") != "cross-site"
                and self.headers.get("X-Requested-With") == "donna-story-app"
                and self.headers.get_content_type() == "application/json")


def main():
    try:
        settings = Settings.from_options(json.loads(Path("/data/options.json").read_text()))
    except (OSError, ValueError, TypeError):
        print("Configure a public HTTPS target, username and password before starting.", file=sys.stderr)
        return 1
    print("Family stories ingress proxy listening on port 8099.", flush=True)
    ProxyServer(("0.0.0.0", 8099), settings).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
