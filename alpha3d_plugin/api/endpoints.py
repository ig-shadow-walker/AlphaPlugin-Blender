"""Typed-ish wrappers over the Alpha3D API.

Every function here BLOCKS on the network and must be called from a
background thread. They read the base URL + token from add-on
preferences on each call so a fresh login (or a URL change in prefs)
takes effect immediately.
"""

from ..preferences import get_prefs
from .client import Alpha3DClient, ApiError


def _client(require_token=True) -> Alpha3DClient:
    prefs = get_prefs()
    token = prefs.token or None
    if require_token and not token:
        raise ApiError(401, "Not connected — log in from the Alpha3D panel first.")
    return Alpha3DClient(prefs.base_url, token)


# ── Alphred sessions / chat ──────────────────────────────────────────


def create_session(surface="blender", title=None):
    """Create a new Alphred session tagged with this surface."""
    return _client().post("/alphred/sessions", {"title": title, "surface": surface})


def send_message_stream(session_id, text, on_event, should_stop=None, attachment_ids=None):
    """Stream an Alphred turn. `on_event(name, data_str)` fires per SSE frame
    on the calling (background) thread."""
    body = {"text": text}
    if attachment_ids:
        body["attachment_ids"] = attachment_ids
    _client().stream(
        f"/alphred/sessions/{session_id}/messages", body, on_event, should_stop
    )


def submit_tool_result(session_id, tool_use_id, result):
    """Feed a client-executed tool's result back into a paused turn.

    NOTE: the backend endpoint POST /alphred/sessions/:id/tool-result is
    NOT implemented yet (it needs the turn-loop pause/resume refactor and
    is only useful once bpy tools exist). This wrapper is here so the
    client side is ready; calling it today will 404.
    """
    return _client().post(
        f"/alphred/sessions/{session_id}/tool-result",
        {"toolUseId": tool_use_id, "result": result},
    )


# ── Library / account ────────────────────────────────────────────────


def list_posts(page=1, limit=12, status=None):
    """List the user's generations for the Library tab.

    TODO(phase-2): confirm the exact REST path. `list_my_posts` is an
    Alphred tool today; the standalone REST list lives under gen3d.
    """
    query = f"?page={page}&limit={limit}"
    if status:
        query += f"&status={status}"
    return _client().get(f"/gen3d/user-posts{query}")


def get_balance():
    """Alphred Agent credit balance."""
    return _client().get("/alphred/credits/balance")
