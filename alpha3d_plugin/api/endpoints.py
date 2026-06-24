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


# ── Generation: text / image → 3D ────────────────────────────────────
#
# The backend has NO prompt-only text-to-3D: alpha-5-text_to_3d still
# requires an image. The web app makes a FLUX text→image first, then
# feeds that image into /alpha-5/create. We mirror that two-step flow.


def text_to_image(prompt):
    """FLUX text→image. Returns {success, imageData: <base64 JPEG>, ...}.

    staticEnhancement=True (the web default) applies the black-bg / soft-
    light treatment that makes a clean single-subject input for 3D.
    """
    return _client().post(
        "/img-gen/text-to-image",
        {
            "prompt": prompt,
            "resolution": "1K",
            "ratio": "square",
            "staticEnhancement": True,
        },
    )


def submit_generation(body):
    """POST /alpha-5/create. `body` carries generationType + imageBase64
    (or imageUrl) + options. Returns {success, data:{post, hunyuanJobId}};
    poll data.post.id. Do NOT include `user` — the backend sets it from
    the JWT."""
    return _client().post("/alpha-5/create", body)


def poll_generation(post_id):
    """POST /alpha-5/poll/:id — actively queries Tencent + mirrors result
    files to Spaces. `post_id` is the post id from submit_generation, not
    the Hunyuan job id. Done when data.post.status == 'completed'."""
    return _client().post(f"/alpha-5/poll/{post_id}")


def get_post(post_id):
    """GET /alpha-5/posts/:id — owner-gated, plan-independent. Carries
    data.downloadUrls.objFiles.glb (a presigned, directly-downloadable
    Spaces URL, ~300s expiry)."""
    return _client().get(f"/alpha-5/posts/{post_id}")


def download_file(url, dest_path):
    """Download a presigned result URL to a local path. No auth header
    (the asset host is Spaces, not our API)."""
    return Alpha3DClient("", None, timeout=180).download(url, dest_path)
