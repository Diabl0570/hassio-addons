import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("stories_proxy", Path(__file__).parents[1] / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proxy
spec.loader.exec_module(proxy)
INGRESS = "/api/hassio_ingress/test_token"


class Upstream(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.calls.append((self.command, self.path, dict(self.headers), body))
        self.send_response(302 if self.path.startswith("/redirect") else 401 if self.path == "/auth-error" else 200)
        if self.path.startswith("/redirect"):
            self.send_header("Location", "/next?page=2" if self.path == "/redirect" else "https://other.example/")
        self.send_header("Set-Cookie", "upstream-secret=do-not-forward")
        self.send_header("WWW-Authenticate", "Basic")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "7")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"sample\x00")

    do_POST = do_GET
    do_HEAD = do_GET


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cert, key = [str(Path(cls.temp.name) / n) for n in ("cert.pem", "key.pem")]
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", key, "-out", cert, "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.upstream.socket = context.wrap_socket(cls.upstream.socket, server_side=True)
        cls.trust = ssl.create_default_context(cafile=cert)
        cls.upstream_thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.upstream_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.settings = proxy.Settings.from_options({"target_url": "https://stories.example", "username": "family", "password": "secret"})
        self.server = proxy.ProxyServer(("127.0.0.1", 0), self.settings, accepted_peer="127.0.0.1",
            connection_factory=lambda host, timeout: http.client.HTTPSConnection("localhost", self.upstream.server_port, context=self.trust, timeout=timeout))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        Upstream.calls.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path="/", method="GET", headers=None, body=None):
        h = {"Host": "ha.example:8123", "X-Ingress-Path": INGRESS, **(headers or {})}
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def post_headers(self):
        return {"Origin": "http://ha.example:8123", "Content-Type": "application/json", "X-Requested-With": "donna-story-app"}

    def test_default_rejects_non_supervisor_peer(self):
        self.server.accepted_peer = proxy.SUPERVISOR_IP
        self.assertEqual(self.request()[0], 403)
        self.assertFalse(Upstream.calls)

    def test_requires_ingress_header_even_from_trusted_peer(self):
        self.assertEqual(self.request(headers={"X-Ingress-Path": ""})[0], 403)
        self.assertFalse(Upstream.calls)

    def test_binary_path_query_and_server_side_credentials(self):
        status, headers, body = self.request("/assets/page.png?v=3", headers={
            "Authorization": "Bearer ha-secret", "Cookie": "ingress_session=secret", "X-Remote-User-Id": "user-secret",
            "X-Forwarded-For": "sensitive-client", "Referer": "https://ha.example/private"})
        self.assertEqual((status, body), (200, b"sample\x00"))
        method, path, forwarded, _ = Upstream.calls[0]
        self.assertEqual(path, "/assets/page.png?v=3")
        self.assertEqual(forwarded["Authorization"], "Basic " + base64.b64encode(b"family:secret").decode())
        self.assertEqual(forwarded["X-Ingress-Path"], INGRESS)
        self.assertFalse({"Cookie", "X-Remote-User-Id", "X-Forwarded-For", "Referer"} & forwarded.keys())
        self.assertNotIn("Set-Cookie", headers)
        self.assertNotIn("WWW-Authenticate", headers)

    def test_same_origin_json_post_rewrites_origin(self):
        self.assertEqual(self.request("/api/v1/library", "POST", self.post_headers(), b'{"library":{}}')[0], 200)
        method, path, headers, body = Upstream.calls[0]
        self.assertEqual((method, headers["Origin"], body), ("POST", "https://stories.example", b'{"library":{}}'))

    def test_foreign_missing_or_malformed_origin_never_reaches_upstream(self):
        for origin in ("https://evil.example", "null", "", "https://[", "http://user@ha.example:8123"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("/api/v1/library", "POST", {**self.post_headers(), "Origin": origin}, b"{}")[0], 403)
        self.assertFalse(Upstream.calls)

    def test_form_and_cross_site_posts_are_rejected(self):
        for changes in ({"Content-Type": "application/x-www-form-urlencoded"}, {"X-Requested-With": ""}, {"Sec-Fetch-Site": "cross-site"}, {"X-Forwarded-Proto": "https"}):
            self.assertEqual(self.request("/api/v1/library", "POST", {**self.post_headers(), **changes}, b"{}")[0], 403)
        self.assertFalse(Upstream.calls)

    def test_preflight_and_external_request_target_rejected(self):
        self.assertEqual(self.request(method="OPTIONS")[0], 403)
        self.assertEqual(self.request("https://evil.example/")[0], 400)
        self.assertFalse(Upstream.calls)

    def test_large_or_chunked_body_rejected_before_read(self):
        for changes, code in (({"Content-Length": str(proxy.MAX_BODY + 1)}, 413), ({"Transfer-Encoding": "chunked"}, 400)):
            self.assertEqual(self.request("/api/v1/library", "POST", {**self.post_headers(), **changes})[0], code)
        self.assertFalse(Upstream.calls)

    def test_redirects_stay_inside_ingress(self):
        self.assertEqual(self.request("/redirect")[1]["Location"], INGRESS + "/next?page=2")
        self.assertEqual(self.request("/redirect-outside")[0], 502)

    def test_upstream_auth_error_does_not_trigger_browser_login(self):
        status, headers, _ = self.request("/auth-error")
        self.assertEqual(status, 502)
        self.assertNotIn("WWW-Authenticate", headers)

    def test_head_preserves_length_without_body(self):
        status, headers, body = self.request(method="HEAD")
        self.assertEqual((status, body, headers["Content-Length"]), (200, b"", "7"))

    def test_tls_failure_is_not_bypassed(self):
        self.server.connection_factory = lambda host, timeout: http.client.HTTPSConnection("localhost", self.upstream.server_port, timeout=timeout)
        self.assertEqual(self.request()[0], 502)
        self.assertFalse(Upstream.calls)

    def test_configuration_rejects_non_https_credentials_and_url_tricks(self):
        for target in ("http://stories.example", "https://127.0.0.1", "https://stories.example:8443", "https://user:secret@stories.example", "https://stories.example/path", "https://stories.example?url=https://evil.example"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                proxy.Settings.from_options({"target_url": target, "username": "family", "password": "secret"})
        with self.assertRaises(ValueError):
            proxy.Settings.from_options({"target_url": "https://stories.example", "username": "family", "password": ""})

    def test_private_dns_answers_are_not_connected(self):
        with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]), patch.object(socket, "create_connection") as connect:
            with self.assertRaises(OSError):
                proxy.PublicHTTPSConnection("stories.example").connect()
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
