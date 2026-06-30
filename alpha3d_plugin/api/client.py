"""Minimal HTTP client built on the stdlib only.

Blender ships its own Python with no pip packages guaranteed, so we
cannot depend on `requests`. `urllib.request` covers JSON requests and
SSE streaming. All calls here are BLOCKING and must run on a background
thread (see `mainthread.run_on_main_thread` for marshalling results
back to the UI).
"""

import json
import socket
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
        except (TimeoutError, socket.timeout):
            # A read timeout on a long synchronous endpoint (FLUX, create).
            # socket.timeout IS TimeoutError on 3.10+, but it is NOT a
            # URLError, so it would otherwise escape as a bare repr.
            raise ApiError(
                0,
                "Timed out waiting for the server. It may still be working — "
                "open the Library tab to check.",
            )
        except urllib.error.URLError as exc:
            # A wrapped timeout surfaces here as URLError(reason=timeout).
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ApiError(
                    0,
                    "Timed out waiting for the server. It may still be working — "
                    "open the Library tab to check.",
                )
            raise ApiError(0, f"Connection failed: {reason}")

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body)

    # ── binary download ──────────────────────────────────────────────

    def download(self, url, dest_path, timeout=180, progress_cb=None):
        """Stream an ABSOLUTE url to `dest_path`. Returns `dest_path`.

        For presigned result URLs (DigitalOcean Spaces): the request is
        built from `url` directly (not base_url + path) and deliberately
        sends NO Authorization header — the signature lives in the query
        string and the asset host is not our API. A longer default
        timeout covers multi-MB GLBs.

        If `progress_cb` is given it is called as progress_cb(downloaded,
        total) on THIS (worker) thread as bytes arrive — `total` is the
        Content-Length, or 0 when the server didn't send one.
        """
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                try:
                    total = int(resp.getheader("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                downloaded = 0
                if progress_cb:
                    progress_cb(0, total)
                with open(dest_path, "wb") as out:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, f"Download failed: {exc.reason}")
        except (TimeoutError, socket.timeout):
            raise ApiError(0, "Download timed out.")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiError(0, f"Download failed: {reason}")
        return dest_path

    # ── binary upload ─────────────────────────────────────────────────

    def upload(self, url, src_path, content_type=None, timeout=600):
        """PUT a local file to an ABSOLUTE presigned URL (DigitalOcean
        Spaces). Sends NO Authorization header — the SigV4 signature is in
        the query string and extra headers would break it. `content_type`
        MUST match what was baked into the presign. Generous timeout covers
        large meshes (up to 200 MB)."""
        with open(src_path, "rb") as f:
            data = f.read()
        headers = {"Content-Length": str(len(data))}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, f"Upload failed: {exc.reason}")
        except (TimeoutError, socket.timeout):
            raise ApiError(0, "Upload timed out. Try a smaller mesh.")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiError(0, f"Upload failed: {reason}")
        return True

    # ── Server-Sent Events ───────────────────────────────────────────

    def stream(self, path, body, on_event, should_stop=None):
        """POST and parse the SSE response frame by frame.

        Generic Server-Sent-Events helper (no current caller — kept as a
        reusable client capability for future streaming endpoints).
        `on_event(name, data_str)` is called per frame, ON THIS (background)
        THREAD — the callback is responsible for marshalling to the main
        thread. `should_stop()` is polled between frames so the caller can
        abort a long stream.
        """
        # No timeout: a streamed response can take minutes between frames.
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
