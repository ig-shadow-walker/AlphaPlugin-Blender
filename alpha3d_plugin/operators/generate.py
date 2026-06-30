"""Text / Image to 3D — mirrors the web app's GenerationBox flow.

Text path (with the preview gate, like the website's "Control Mode"):

    prompt -> FLUX text->image (free)  ->  PREVIEW gate
        Regenerate -> new FLUX image (free, new seed)
        Create 3D  -> rembg -> /alpha-5/create -> poll -> download GLB -> import

Image path (a reference image is attached) skips FLUX and the gate, exactly
like the website:

    image  -> rembg -> /alpha-5/create -> poll -> download GLB -> import

Threading rules: ALL network runs on a daemon thread; `bpy` (and the preview
image collection) is touched ONLY on the main thread via
mainthread.run_on_main_thread. The 3D quality / PBR / polygon fields are read
from props on the main thread before a worker is spawned.
"""

import base64
import os
import tempfile
import threading
import time

import bpy
import bpy.utils.previews

from . import library, notice
from .. import glbutil, mainthread
from ..api import endpoints
from ..api.client import ApiError
from ..constants import QUALITY_TABLE
from ..preferences import is_connected

# Hunyuan rejects inputs over 8 MB. Guard the raw file so the user gets a
# friendly message instead of a server 400.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# A generation usually finishes in 1-3 min; cap the wait generously.
_POLL_INTERVAL_SECONDS = 8
_POLL_TIMEOUT_SECONDS = 600
# Human-friendly labels for the backend's status stages.
_STAGE_LABELS = {
    "new": "queued",
    "starting": "starting",
    "sculpting": "sculpting",
    "meshing": "building mesh",
    "texturing": "texturing",
    "extracting_mesh": "extracting mesh",
    "extracting_textured": "extracting model",
}

# Preview image: a single-entry preview collection the panel draws via
# template_icon. Created lazily on the main thread, freed in unregister.
_preview_coll = None
_PREVIEW_KEY = "alpha3d_preview"
# Base64 of the currently-previewed image, used by the Create 3D step. Only
# one generation runs at a time, so a module global is sufficient (and avoids
# stuffing multi-MB strings into a Blender property).
_preview_b64 = None
# Set True while a 3D job is polling; the worker checks it to stop early.
_gen_active = False


# ── main-thread helpers ──────────────────────────────────────────────


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _set_stage(stage, status=None):
    """Set the generation stage (+ optional status line). Main thread only."""
    props = _props()
    if props:
        props.gen_stage = stage
        if status is not None:
            props.gen_status = status
    mainthread.tag_redraw_all()


def _update_status(text):
    """Update only the status line, leaving the stage as-is. Main thread only."""
    props = _props()
    if props:
        props.gen_status = text
    mainthread.tag_redraw_all()


def _status_async(text):
    """Schedule a status-line update from the worker thread."""
    mainthread.run_on_main_thread(lambda t=text: _update_status(t))


def _stage_async(stage, status=None):
    """Schedule a stage change from the worker thread."""
    mainthread.run_on_main_thread(lambda s=stage, t=status: _set_stage(s, t))


# ── preview image (main thread only) ─────────────────────────────────


def _ensure_preview_coll():
    global _preview_coll
    if _preview_coll is None:
        _preview_coll = bpy.utils.previews.new()
    return _preview_coll


def _load_preview(filepath):
    """Load an image file into the preview collection. Main thread only."""
    coll = _ensure_preview_coll()
    coll.clear()  # only ever one preview at a time
    coll.load(_PREVIEW_KEY, filepath, "IMAGE")
    mainthread.tag_redraw_all()


def _clear_preview():
    """Drop the preview image. Main thread only."""
    if _preview_coll is not None:
        _preview_coll.clear()
    mainthread.tag_redraw_all()


def get_preview_icon_id():
    """icon_id for the panel's template_icon, or 0 if no preview is loaded."""
    if _preview_coll is not None and _PREVIEW_KEY in _preview_coll:
        return _preview_coll[_PREVIEW_KEY].icon_id
    return 0


def _import_glb(filepath):
    """Import the downloaded GLB into the scene. Main thread only."""
    global _preview_b64
    try:
        mainthread.run_in_view3d_context(
            lambda: bpy.ops.import_scene.gltf(filepath=filepath)
        )
    except Exception as exc:  # noqa: BLE001
        _set_stage("IDLE", f"Import failed: {exc!r}")
        return
    _preview_b64 = None  # release the (multi-MB) cached preview image
    _clear_preview()
    _set_stage("IDLE", "Model imported into the scene.")
    notice.show("Your 3D model is ready.")


# ── field assembly (main thread — reads props) ───────────────────────


def build_fields(props, generation_type):
    """Assemble the alpha-5 create payload's quality fields from props.

    Mirrors generationBox.tsx: generateType / octreeResolution / faceCount per
    tier, PBR forced off for Low-Poly (+ hunyuanModel 3.0, explicit
    polygonType, quadExport). `generation_type` is the post kind
    ('alpha-5-text_to_3d' or 'alpha-5-image_to_3d').
    """
    tier = QUALITY_TABLE.get(props.gen_quality, QUALITY_TABLE["HIGH_RES"])
    face = int(props.gen_face_count) or tier["face_default"]
    face = max(tier["face_min"], min(tier["face_max"], face))
    fields = {
        "generationType": generation_type,
        "generateType": tier["generate_type"],
        "octreeResolution": tier["octree"],
        "faceCount": face,
    }
    if props.gen_quality == "LOW_POLY":
        fields["enablePBR"] = False
        fields["hunyuanModel"] = "3.0"
        fields["polygonType"] = (
            "quadrilateral" if props.gen_poly_type == "QUAD" else "triangle"
        )
        fields["quadExport"] = props.gen_poly_type == "QUAD"
    else:
        fields["enablePBR"] = bool(props.gen_enable_pbr)
    return fields


# ── worker thread: FLUX preview ──────────────────────────────────────


def _run_flux_preview(prompt):
    """Worker: generate the FLUX preview image and enter the PREVIEW gate."""
    global _preview_b64
    try:
        res = endpoints.text_to_image(prompt) or {}
        b64 = res.get("imageData")
        if not b64:
            raise ApiError(0, "Image generation returned no image.")
        _preview_b64 = b64
        path = os.path.join(tempfile.gettempdir(), "alpha3d_preview.jpg")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        mainthread.run_on_main_thread(lambda p=path: _on_preview_ready(p))
    except ApiError as exc:
        _stage_async("IDLE", f"Error: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        _stage_async("IDLE", f"Error: {exc!r}")


def _on_preview_ready(path):
    """Main thread: show the new preview image and open the gate."""
    try:
        _load_preview(path)
    except Exception as exc:  # noqa: BLE001
        _set_stage("IDLE", f"Could not display the preview: {exc!r}")
        return
    _set_stage("PREVIEW", "Review the image, then Regenerate or Create 3D.")


# ── worker thread: image -> 3D ───────────────────────────────────────


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
        if not _gen_active:
            raise ApiError(0, "Cancelled.")
        res = endpoints.poll_generation(post_id) or {}
        data = res.get("data", {}) or {}
        status = (data.get("post", {}) or {}).get("status")
        if status == "completed":
            detail = endpoints.get_post(post_id) or {}
            glb = (
                (
                    ((detail.get("data", {}) or {}).get("downloadUrls", {}) or {}).get(
                        "objFiles", {}
                    )
                    or {}
                ).get("glb")
            )
            if not glb:
                raise ApiError(0, "Model finished but no GLB URL was returned.")
            return glb
        if status == "error":
            raise ApiError(0, "Generation failed on the server.")
        _status_async(
            f"Generating 3D... ({_STAGE_LABELS.get(status, status or 'working')})"
        )
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise ApiError(0, "Timed out waiting for the model.")


def _run_generation(params):
    """Worker: rembg (best-effort) -> create -> poll -> download -> import."""
    global _gen_active
    _gen_active = True
    try:
        img_b64 = params["image_b64"]

        # Background removal — best-effort, exactly like the web app, which
        # falls back to the original image if rembg fails.
        try:
            _status_async("Removing background...")
            rb = endpoints.remove_background(img_b64) or {}
            cleaned = (rb.get("data", {}) or {}).get("image")
            if cleaned:
                img_b64 = cleaned
        except Exception:  # noqa: BLE001
            pass

        body = dict(params["fields"])
        body["imageBase64"] = img_b64
        body["guidanceScale"] = -1
        body["selectedModel"] = "alpha-5"
        body["advancedControl"] = True
        # Provenance: tag every Blender-originated generation so the backend
        # records origin='blender' (web omits this → defaults to USER).
        body["origin"] = "blender"
        if params.get("prompt"):
            body["prompt"] = params["prompt"]
        # postTitle: the prompt for text-to-3D, else a name derived from the
        # image file (the web app always sends a title — without one the post
        # is stored as "Untitled").
        title = (params.get("title") or params.get("prompt") or "").strip()
        if title:
            body["postTitle"] = title[:100]

        _status_async("Submitting to Alpha3D...")
        created = endpoints.submit_generation(body) or {}
        post_id = (created.get("data", {}) or {}).get("post", {}).get("id")
        if not post_id:
            raise ApiError(0, "Submit did not return a post id.")

        # Surface the new job in the Library immediately with its live status.
        mainthread.run_on_main_thread(library.request_refresh)

        _status_async("Generating 3D... (queued)")
        glb_url = _poll_until_glb(post_id)

        _status_async("Downloading model...")
        dest = os.path.join(tempfile.gettempdir(), f"alpha3d_{post_id}.glb")
        endpoints.download_file(glb_url, dest)
        glbutil.sanitize_glb(dest)  # trim trailing bytes Blender's loader rejects

        mainthread.run_on_main_thread(lambda p=dest: _import_glb(p))
    except ApiError as exc:
        _stage_async("IDLE", f"Error: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        _stage_async("IDLE", f"Error: {exc!r}")
    finally:
        _gen_active = False


def _spawn(target, *args, name="Alpha3D-gen"):
    threading.Thread(target=target, args=args, daemon=True, name=name).start()


# ── operators ──────────────────────────────────────────────────────────


class ALPHA3D_OT_generate(bpy.types.Operator):
    bl_idname = "alpha3d.generate"
    bl_label = "Generate"
    bl_description = (
        "Generate a 3D model. With a prompt you preview the image first; "
        "with a reference image it goes straight to 3D"
    )

    def execute(self, context):
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.gen_stage in ("IMAGING", "GENERATING"):
            self.report({"WARNING"}, "A job is already running.")
            return {"CANCELLED"}

        prompt = (props.gen_prompt or "").strip()
        image_path = (props.gen_image_path or "").strip()

        # A reference image wins and skips the FLUX preview (web app parity).
        if image_path:
            abs_image = bpy.path.abspath(image_path)
            if not os.path.isfile(abs_image):
                self.report({"ERROR"}, "Reference image file not found.")
                return {"CANCELLED"}
            try:
                image_b64 = _read_image_b64(abs_image)
            except ApiError as exc:
                self.report({"ERROR"}, exc.message)
                return {"CANCELLED"}
            stem = os.path.splitext(os.path.basename(abs_image))[0]
            params = {
                "image_b64": image_b64,
                "fields": build_fields(props, "alpha-5-image_to_3d"),
                "prompt": prompt,
                "title": prompt or stem,
            }
            props.gen_stage = "GENERATING"
            props.gen_status = "Starting..."
            _spawn(_run_generation, params)
            return {"FINISHED"}

        if prompt:
            props.gen_stage = "IMAGING"
            props.gen_status = "Imagining your prompt..."
            _spawn(_run_flux_preview, prompt, name="Alpha3D-flux")
            return {"FINISHED"}

        self.report({"ERROR"}, "Enter a prompt or choose a reference image.")
        return {"CANCELLED"}


class ALPHA3D_OT_regenerate_image(bpy.types.Operator):
    bl_idname = "alpha3d.regenerate_image"
    bl_label = "Regenerate Image"
    bl_description = "Generate a different image from the same prompt (free)"

    def execute(self, context):
        props = context.window_manager.alpha3d
        prompt = (props.gen_prompt or "").strip()
        if not prompt:
            self.report({"ERROR"}, "No prompt to regenerate from.")
            return {"CANCELLED"}
        props.gen_stage = "IMAGING"
        props.gen_status = "Imagining a new image..."
        _spawn(_run_flux_preview, prompt, name="Alpha3D-flux")
        return {"FINISHED"}


class ALPHA3D_OT_create_3d(bpy.types.Operator):
    bl_idname = "alpha3d.create_3d"
    bl_label = "Create 3D"
    bl_description = "Turn the previewed image into a 3D model and import it"

    def execute(self, context):
        props = context.window_manager.alpha3d
        if props.gen_stage != "PREVIEW" or not _preview_b64:
            self.report({"ERROR"}, "No previewed image to use.")
            return {"CANCELLED"}
        params = {
            "image_b64": _preview_b64,
            "fields": build_fields(props, "alpha-5-text_to_3d"),
            "prompt": (props.gen_prompt or "").strip(),
        }
        props.gen_stage = "GENERATING"
        props.gen_status = "Starting..."
        _spawn(_run_generation, params)
        return {"FINISHED"}


class ALPHA3D_OT_discard_preview(bpy.types.Operator):
    bl_idname = "alpha3d.discard_preview"
    bl_label = "Discard"
    bl_description = "Discard the previewed image and start over"

    def execute(self, context):
        global _preview_b64
        props = context.window_manager.alpha3d
        _preview_b64 = None
        _clear_preview()
        props.gen_stage = "IDLE"
        props.gen_status = ""
        return {"FINISHED"}


classes = (
    ALPHA3D_OT_generate,
    ALPHA3D_OT_regenerate_image,
    ALPHA3D_OT_create_3d,
    ALPHA3D_OT_discard_preview,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _preview_coll, _preview_b64, _gen_active
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _gen_active = False
    _preview_b64 = None
    if _preview_coll is not None:
        bpy.utils.previews.remove(_preview_coll)
        _preview_coll = None
