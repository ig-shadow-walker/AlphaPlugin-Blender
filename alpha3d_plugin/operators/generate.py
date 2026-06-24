"""Text / Image to 3D — generate a model and import it into the scene.

Flow (all network on a daemon thread; bpy touched ONLY on the main
thread via mainthread.run_on_main_thread):

  text mode : FLUX text->image  ->  /alpha-5/create  ->  poll  ->  GLB
  image mode:                       /alpha-5/create  ->  poll  ->  GLB
  then: download the presigned GLB to a temp file and import it.

The backend has no prompt-only text-to-3D, so the text path generates a
reference image first (mirrors the web app), then runs image-to-3D.
"""

import base64
import os
import tempfile
import threading
import time

import bpy

from .. import mainthread
from ..api import endpoints
from ..api.client import ApiError
from ..preferences import is_connected

# Hunyuan rejects inputs over 8 MB. Guard the raw file so the user gets a
# friendly message instead of a server 400.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# A generation usually finishes in 1-3 min; cap the wait generously.
_POLL_INTERVAL_SECONDS = 8
_POLL_TIMEOUT_SECONDS = 600
# Human-friendly labels for the backend's status stages.
_STAGE_LABELS = {
    "new": "Queued",
    "starting": "Starting",
    "sculpting": "Sculpting",
    "meshing": "Building mesh",
    "texturing": "Texturing",
    "extracting_mesh": "Extracting mesh",
    "extracting_textured": "Extracting model",
}


# ── main-thread helpers ──────────────────────────────────────────────


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _set_status(text, running=True):
    """Update the progress line. Main thread only."""
    props = _props()
    if props:
        props.gen_status = text
        props.gen_is_running = running
    mainthread.tag_redraw_all()


def _status_async(text):
    """Schedule a progress update from the worker thread."""
    mainthread.run_on_main_thread(lambda t=text: _set_status(t, running=True))


def _import_glb(filepath):
    """Import the downloaded GLB into the scene. Main thread only."""
    try:
        bpy.ops.import_scene.gltf(filepath=filepath)
    except Exception as exc:  # noqa: BLE001
        _set_status(f"Import failed: {exc!r}", running=False)
        return
    _set_status("Model imported into the scene.", running=False)


# ── worker thread ────────────────────────────────────────────────────


def _read_image_b64(abs_path):
    """Read an on-disk image and base64-encode it. Worker thread (no bpy)."""
    if not os.path.isfile(abs_path):
        raise ApiError(0, "Reference image file not found.")
    size = os.path.getsize(abs_path)
    if size > _MAX_IMAGE_BYTES:
        raise ApiError(0, "Reference image is larger than 8 MB. Use a smaller image.")
    with open(abs_path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _poll_until_glb(post_id):
    """Drive the job to completion and return the presigned GLB URL."""
    deadline = time.time() + _POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        if not _is_running():
            raise ApiError(0, "Cancelled.")
        res = endpoints.poll_generation(post_id) or {}
        data = res.get("data", {}) or {}
        post = data.get("post", {}) or {}
        status = post.get("status")
        if status == "completed":
            detail = endpoints.get_post(post_id) or {}
            glb = (
                (detail.get("data", {}) or {})
                .get("downloadUrls", {})
                .get("objFiles", {})
                .get("glb")
            )
            if not glb:
                raise ApiError(0, "Model finished but no GLB URL was returned.")
            return glb
        if status == "error":
            raise ApiError(0, "Generation failed on the server.")
        _status_async(f"Generating 3D… ({_STAGE_LABELS.get(status, status or 'working')})")
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise ApiError(0, "Timed out waiting for the model.")


def _run_generation(params):
    """Worker-thread body: build input, submit, poll, download, import."""
    try:
        if params["mode"] == "image":
            image_b64 = _read_image_b64(params["image_path"])
            body = {
                "generationType": "alpha-5-image_to_3d",
                "imageBase64": image_b64,
            }
            if params["prompt"]:
                body["postTitle"] = params["prompt"][:120]
        else:  # text
            _status_async("Generating a reference image…")
            res = endpoints.text_to_image(params["prompt"]) or {}
            image_b64 = res.get("imageData")
            if not image_b64:
                raise ApiError(0, "Image generation returned no image.")
            body = {
                "generationType": "alpha-5-text_to_3d",
                "prompt": params["prompt"],
                "imageBase64": image_b64,
            }

        body["generateType"] = "Normal"
        body["enablePBR"] = params["enable_pbr"]

        _status_async("Submitting to Alpha3D…")
        created = endpoints.submit_generation(body) or {}
        post_id = (created.get("data", {}) or {}).get("post", {}).get("id")
        if not post_id:
            raise ApiError(0, "Submit did not return a post id.")

        _status_async("Generating 3D… (queued)")
        glb_url = _poll_until_glb(post_id)

        _status_async("Downloading model…")
        dest = os.path.join(tempfile.gettempdir(), f"alpha3d_{post_id}.glb")
        endpoints.download_file(glb_url, dest)

        mainthread.run_on_main_thread(lambda p=dest: _import_glb(p))
    except ApiError as exc:
        mainthread.run_on_main_thread(
            lambda e=exc: _set_status(f"Error: {e.message}", running=False)
        )
    except Exception as exc:  # noqa: BLE001
        mainthread.run_on_main_thread(
            lambda e=exc: _set_status(f"Error: {e!r}", running=False)
        )


def _is_running():
    props = _props()
    return bool(props and props.gen_is_running)


# ── operator ──────────────────────────────────────────────────────────


class ALPHA3D_OT_generate_3d(bpy.types.Operator):
    bl_idname = "alpha3d.generate_3d"
    bl_label = "Generate 3D"
    bl_description = (
        "Generate a 3D model from a text prompt or a reference image, "
        "then import it into the scene"
    )

    def execute(self, context):
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.gen_is_running:
            self.report({"WARNING"}, "A generation is already running.")
            return {"CANCELLED"}

        prompt = (props.gen_prompt or "").strip()
        image_path = (props.gen_image_path or "").strip()

        # An image (when given) wins: image-to-3D is more direct than the
        # text->image->3D path. The prompt then becomes an optional title.
        if image_path:
            # Resolve `//`-relative paths on the main thread (touches
            # bpy.data) so the worker only sees an absolute path.
            abs_image = bpy.path.abspath(image_path)
            if not os.path.isfile(abs_image):
                self.report({"ERROR"}, "Reference image file not found.")
                return {"CANCELLED"}
            mode = "image"
        elif prompt:
            abs_image = None
            mode = "text"
        else:
            self.report({"ERROR"}, "Enter a prompt or choose a reference image.")
            return {"CANCELLED"}

        props.gen_is_running = True
        props.gen_status = "Starting…"
        params = {
            "mode": mode,
            "prompt": prompt,
            "image_path": abs_image,
            "enable_pbr": bool(props.gen_enable_pbr),
        }
        threading.Thread(
            target=_run_generation, args=(params,), daemon=True, name="Alpha3D-generate"
        ).start()
        return {"FINISHED"}


classes = (ALPHA3D_OT_generate_3d,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
