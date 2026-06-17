"""Browser-loopback HTTP listener for login.

The plugin can't safely handle the user's password, so login happens in
the browser: we open `https://alpha3d.io/plugin-auth?port=<PORT>`, the
web app (where the user is already / gets logged in) POSTs the existing
JWT back to `http://127.0.0.1:<PORT>/callback`, and we capture it here.

The server binds to an OS-assigned port on loopback only, serves until
it gets one token (or times out), then shuts down. It runs on a daemon
thread; the captured token is handed to a callback that marshals it to
Blender's main thread.
"""

import http.server
import json
import socketserver
import threading
import time

from ..constants import LOGIN_TIMEOUT_SECONDS


def _make_handler():
    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        # Silence the default stderr request logging.
        def log_message(self, *args):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            # CORS preflight from the https://alpha3d.io page.
            self.send_response(204)
            self._cors()
            self.end_headers()

        def _finish(self, token):
            self.server.received_token = token
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><meta charset=utf-8>"
                b"<title>Alpha3D</title>"
                b"<body style='font-family:sans-serif;text-align:center;padding:48px'>"
                b"<h2>Connected.</h2><p>You can close this tab and return to Blender.</p>"
                b"</body>"
            )

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            token = None
            try:
                payload = json.loads(raw) if raw else {}
                token = payload.get("accessToken") or payload.get("token")
            except Exception:
                token = None
            if not token:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return
            self._finish(token)

        def do_GET(self):
            # Convenience fallback: token passed as ?token= on a GET.
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            token = (qs.get("token") or qs.get("accessToken") or [None])[0]
            if not token:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return
            self._finish(token)

    return _CallbackHandler


def start_loopback(on_token, on_timeout=None, timeout=LOGIN_TIMEOUT_SECONDS):
    """Start the listener; returns the chosen port immediately.

    `on_token(token)` fires (on the listener thread) once a token arrives;
    `on_timeout()` fires if none arrives within `timeout` seconds.
    """
    # Port 0 → OS picks a free port. 127.0.0.1 keeps it off the network.
    server = socketserver.TCPServer(("127.0.0.1", 0), _make_handler())
    server.received_token = None
    server.timeout = 1  # handle_request() wakes up every second to re-check
    port = server.server_address[1]

    def _serve():
        started = time.time()
        try:
            while server.received_token is None:
                if time.time() - started > timeout:
                    break
                server.handle_request()  # blocks up to server.timeout
        finally:
            token = server.received_token
            try:
                server.server_close()
            except Exception:
                pass
            if token:
                on_token(token)
            elif on_timeout:
                on_timeout()

    threading.Thread(target=_serve, daemon=True, name="Alpha3D-loopback").start()
    return port
