"""Typed-ish wrappers over the Alpha3D API.

Every function here BLOCKS on the network and must be called from a
background thread. They read the base URL + token from add-on
preferences on each call so a fresh login (or a URL change in prefs)
takes effect immediately.
"""

from ..preferences import get_prefs
from .client import Alpha3DClient, ApiError


def _client(require_token=True, timeout=30) -> Alpha3DClient:
    prefs = get_prefs()
    token = prefs.token or None
    if require_token and not token:
        raise ApiError(401, "Not connected — log in from the Alpha3D panel first.")
    return Alpha3DClient(prefs.base_url, token, timeout=timeout)


# ── Library / account ────────────────────────────────────────────────


def list_posts(page=1, limit=12, status=None):
    """List the user's generations for the Library tab.

    GET /gen3d/user-posts (JWT, user scoped from the token). Returns
    {success, data:{posts:[{post, presignedUrls}], total, totalPages,
    page, limit}} ordered createdAt DESC. Each element is a
    {post, presignedUrls} pair — presignedUrls carries a directly-
    fetchable thumbnailUrl/imageUrl (3600s). The importable GLB is NOT in
    this list; fetch it per-post via get_post(id) -> objFiles.glb.
    """
    query = f"?page={page}&limit={limit}"
    if status:
        query += f"&status={status}"
    return _client().get(f"/gen3d/user-posts{query}")


def get_balance():
    """Alphred Agent credit balance."""
    return _client().get("/alphred/credits/balance")


# ── 3D source upload (for Smart Topology and other mesh-in ops) ──────
#
# A mesh is too big for inline base64, so it goes onto Spaces first. The
# web app does this by creating an `upload` post, which returns a presigned
# PUT URL inline + the stored object key; that key then becomes `modelUrl`.


def create_upload(file_name, content_type, title=None):
    """POST /gen3d/create {generationType:'upload'} — reserves a Spaces key
    and returns a presigned PUT URL. Returns {success, data:{post, uploadUrl}}
    where data.uploadUrl is the presigned PUT (≈5 min) and
    data.post.texturedMeshUrl is the storage KEY to later send as modelUrl."""
    return _client().post(
        "/gen3d/create",
        {
            "generationType": "upload",
            "uploadFileName": file_name,
            "uploadContentType": content_type,
            "postTitle": title or file_name,
        },
    )


def upload_to_presigned(upload_url, src_path, content_type):
    """PUT a local mesh file to the presigned Spaces URL. No auth header;
    `content_type` must match what create_upload reserved."""
    return Alpha3DClient("", None).upload(upload_url, src_path, content_type)


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
    # FLUX is fully synchronous AND has no job/poll endpoint: the request
    # blocks for the entire image generation (a cold/loaded provider can take
    # minutes). The web app uses no client timeout here, so we go very
    # generous — the call runs on a daemon thread, so the UI stays responsive.
    return _client(timeout=600).post(
        "/img-gen/text-to-image",
        {
            "prompt": prompt,
            "resolution": "1K",
            "ratio": "square",
            "staticEnhancement": True,
            "enhancePrompt": False,
        },
    )


def remove_background(image_b64, model="u2net"):
    """POST /rembg/remove-background — strip the background from a base64
    image before 3D. The web app runs this on the accepted preview so the
    Hunyuan pipeline gets a clean single subject. Returns
    {success, data:{image: <base64>}}. Best-effort: callers fall back to the
    original image when it fails (same as the web app)."""
    # Synchronous server-side background removal — give it a generous window.
    return _client(timeout=300).post(
        "/rembg/remove-background", {"image": image_b64, "model": model}
    )


def submit_generation(body):
    """POST /alpha-5/create. `body` carries generationType + imageBase64
    (or imageUrl) + options. Returns {success, data:{post, hunyuanJobId}};
    poll data.post.id. Do NOT include `user` — the backend sets it from
    the JWT."""
    # Inline imageBase64 means the backend decodes + uploads the image to
    # Spaces and submits to Tencent before responding — all synchronous, so
    # this single request can run well past 30s. The job is queued, not
    # blocking on the actual 3D render (that is what poll_generation is for).
    return _client(timeout=600).post("/alpha-5/create", body)


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


def validate_rigging_pose(images):
    """POST /alpha-5/rigging/validate-pose — advisory T-pose pre-check. `images`
    is a list of {data: <raw base64, no data-URL prefix>, mediaType: 'image/png'}
    (up to 4). Returns {success, data:{isTPose, isHumanoid, pose, confidence,
    reason}}. Persists nothing; safe to call before the paid rigging submit."""
    return _client(timeout=60).post(
        "/alpha-5/rigging/validate-pose", {"images": images}
    )


def download_file(url, dest_path, progress_cb=None):
    """Download a presigned result URL to a local path. No auth header
    (the asset host is Spaces, not our API). `progress_cb(downloaded, total)`
    (optional) is invoked on the calling thread as bytes arrive."""
    return Alpha3DClient("", None, timeout=180).download(
        url, dest_path, progress_cb=progress_cb
    )
