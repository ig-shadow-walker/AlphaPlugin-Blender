"""Minimal HTTP client built on the stdlib only.

Blender ships its own Python with no pip packages guaranteed, so we
cannot depend on `requests`. `urllib.request` covers JSON requests and
SSE streaming. All calls here are BLOCKING and must run on a background
thread (see `mainthread.run_on_main_thread` for marshalling results
back to the UI).
"""

import json
import urllib.error
import urllib.request


class ApiError(Exception):
    """Raised for non-2xx responses or transport failures."""

    def __init__(self, status, message, body=None):
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message
        self.body = body


class Alpha3DClient:
    def __init__(self, base_url, token=None, timeout=30):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self.timeout = timeout

    # ── internals ────────────────────────────────────────────────────

    def _headers(self, extra=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def _build(self, method, path, body=None, accept_sse=False):
        url = self.base_url + path
        data = None
        extra = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            extra["Content-Type"] = "application/json"
        if accept_sse:
            extra["Accept"] = "text/event-stream"
        return urllib.request.Request(
            url, data=data, method=method, headers=self._headers(extra)
        )

    # ── JSON request/response ────────────────────────────────────────

    def request(self, method, path, body=None):
        req = self._build(method, path, body)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = ""
            try:
                raw = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            message = raw
            try:
                parsed = json.loads(raw)
                message = parsed.get("message") or parsed.get("error") or raw
            except Exception:
                parsed = None
            raise ApiError(exc.code, message or exc.reason, parsed or raw)
        except urllib.error.URLError as exc:
            raise ApiError(0, f"Connection failed: {exc.reason}")

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body)

    # ── Server-Sent Events ───────────────────────────────────────────

    def stream(self, path, body, on_event, should_stop=None):
        """POST and parse the SSE response frame by frame.

        `on_event(name, data_str)` is called per frame, ON THIS (background)
        THREAD — the callback is responsible for marshalling to the main
        thread. `should_stop()` is polled between frames so the caller can
        abort a long stream (e.g. when the user closes the chat).
        """
        # No timeout: an agent turn can take minutes between frames.
        req = self._build("POST", path, body, accept_sse=True)
        resp = urllib.request.urlopen(req, timeout=None)
        try:
            event_name = None
            data_lines = []
            for raw_line in resp:
                if should_stop and should_stop():
                    break
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    # blank line terminates a frame
                    if data_lines:
                        on_event(event_name or "message", "\n".join(data_lines))
                    event_name = None
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue  # comment / heartbeat
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip())
            # flush a trailing frame with no terminating blank line
            if data_lines:
                on_event(event_name or "message", "\n".join(data_lines))
        finally:
            resp.close()
