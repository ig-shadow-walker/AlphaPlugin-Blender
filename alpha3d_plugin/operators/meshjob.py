"""Shared pipeline for mesh-in alpha-5 ops (Smart Topology, UV Unwrap, AI
Segmentation): take a source mesh (a selected-object export, or a .glb on
disk), upload it to Spaces, submit the job, poll, download the result(s),
and import into the scene.

The op-specific operator resolves the source on the MAIN THREAD (export can
only run there), builds the /alpha-5/create body, and hands this module two
small main-thread callbacks (set_status / finish). All network runs on a
daemon thread; bpy + the callbacks are marshalled back via
mainthread.run_on_main_thread.

`import_mode`:
  'single' — one result mesh at downloadUrls.objFiles.glb (retopology, UV).
  'parts'  — N separate meshes at downloadUrls.objFiles.part_0..N
             (segmentation); the first part is also mirrored to .glb.
"""

import json
import os
import struct
import tempfile
import threading
import time

import bpy

_GLB_JSON_CHUNK = 0x4E4F534A  # 'JSON'
_GLTF_MODE_TRIANGLES = 4

from . import library, notice
from .. import glbutil, mainthread, sceneimport
from ..api import endpoints
from ..api.client import ApiError

_POLL_INTERVAL_SECONDS = 8
# How long the panel polls for auto-import. Past this the job keeps running
# server-side and is tracked in the Library (request_refresh is called at
# submit), so a timeout is NOT an error — see _JobStillRunning.
_POLL_TIMEOUT_SECONDS = 900
GLB_CONTENT_TYPE = "model/gltf-binary"


class _JobStillRunning(Exception):
    """Poll window elapsed while the job is still processing server-side. Not a
    failure: the job was submitted and the Library tracks it; the user imports
    the result from there when it's done."""


# Cleared on plugin teardown so in-flight poll loops exit promptly.
_alive = True


# ── source resolution (MAIN THREAD) ──────────────────────────────────


def count_selection_triangles(context):
    """Total triangle count of the selected mesh objects, with modifiers
    evaluated. MAIN THREAD ONLY.

    Counts the EVALUATED mesh (what the viewport shows and what
    export_selection_to_glb writes with export_apply=True), so the number we
    check against the cap is exactly the geometry we upload. Mirrors the web
    platform, which counts the viewer mesh's triangles, not the DB face count.
    """
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if not meshes:
        return 0
    depsgraph = context.evaluated_depsgraph_get()
    total = 0
    for obj in meshes:
        eval_obj = obj.evaluated_get(depsgraph)
        me = None
        try:
            me = eval_obj.to_mesh()
        except RuntimeError:
            me = None
        if me is not None:
            try:
                total += _triangles_in_mesh(me)
            finally:
                eval_obj.to_mesh_clear()
        else:
            # Evaluated mesh unavailable for this object — fall back to its
            # base mesh so a dense object that still EXPORTS can't slip past
            # the cap by contributing 0 (undercount would defeat the guard).
            base = getattr(obj, "data", None)
            if base is not None and hasattr(base, "polygons"):
                total += _triangles_in_mesh(base)
    return total


def _triangles_in_mesh(mesh):
    """Triangle count of a bpy Mesh: an n-gon contributes (n - 2) triangles.
    (n - 2) is the triangle count of any simple polygon regardless of the
    triangulation strategy, so it equals what the GLB exporter emits — no
    calc_loop_triangles() needed, works on every Blender version."""
    total = 0
    for poly in mesh.polygons:
        lt = poly.loop_total
        if lt >= 3:
            total += lt - 2
    return total


def export_selection_to_glb(context):
    """Export the selected mesh objects to a temp GLB. MAIN THREAD ONLY.
    Returns (filepath, primary_name); raises ValueError with a friendly
    message when nothing usable is selected or the export fails.

    Modifiers are applied (export_apply=True) so the uploaded geometry is
    exactly what the viewport shows and what count_selection_triangles
    measured. NOTE: this helper is shared by all three mesh ops (retopology,
    UV unwrap, segmentation), so export_apply=True changes what every one of
    them uploads — the evaluated mesh, not the base cage. That is intentional
    (you process the mesh you see) and is required for UV unwrap, where the
    poly cap is checked against the evaluated count. Retopology is built for
    dense input; segmentation is bounded by its 55 MB size cap (the platform's
    only segmentation limit — it has no poly cap either), so neither needs a
    triangle gate.

    Only MESH objects are exported — any armature / empty / light in the
    selection is temporarily deselected so the upstream mesh op never receives
    non-mesh nodes that can trip Tencent's GLB parser."""
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if not meshes:
        raise ValueError("Select a mesh object in the scene first.")
    # Unique per export. Concurrent ops (e.g. a UV job and a Segmentation job)
    # must NOT share one path — the worker reads the file lazily at upload
    # time, so a shared path could upload another job's mesh.
    fd, path = tempfile.mkstemp(suffix=".glb", prefix="alpha3d_src_")
    os.close(fd)
    non_mesh = [o for o in context.selected_objects if o.type != "MESH"]
    try:
        for o in non_mesh:
            try:
                o.select_set(False)
            except (ReferenceError, RuntimeError):
                # Object not in the active view layer (linked / excluded
                # collection). It also won't be reachable by a use_selection
                # export, so leaving it "selected" is harmless.
                pass
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB",
            use_selection=True,
            export_apply=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not export the selection: {exc!r}")
    finally:
        for o in non_mesh:
            try:
                o.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
    active = context.active_object
    primary = active if (active and active in meshes) else meshes[0]
    return path, primary.name


def count_glb_triangles(path):
    """Estimate the triangle count of a binary .glb by reading its glTF JSON
    chunk only (no scene import, no bpy). Sums per-primitive triangles:
    indexed -> indices.count // 3; non-indexed -> POSITION.count // 3, for
    TRIANGLES primitives. Returns None when the file can't be parsed, so the
    caller degrades to the server-side size cap rather than blocking blindly.

    This is the FILE-source counterpart to count_selection_triangles, so a
    dense .glb picked from disk is gated the same way the platform gates an
    uploaded file (it parses the GLB before upload too). Instanced geometry
    is undercounted (rare for these uploads); that only ever under-rejects."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(12)
            if len(header) < 12 or header[:4] != b"glTF":
                return None
            json_bytes = None
            while True:
                chunk_header = fh.read(8)
                if len(chunk_header) < 8:
                    break
                clen, ctype = struct.unpack("<II", chunk_header)
                data = fh.read(clen)
                if len(data) < clen:
                    break
                if ctype == _GLB_JSON_CHUNK:
                    json_bytes = data
                    break
        if json_bytes is None:
            return None
        gltf = json.loads(json_bytes.decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return None
    accessors = gltf.get("accessors") or []
    total = 0
    for mesh in (gltf.get("meshes") or []):
        for prim in (mesh.get("primitives") or []):
            if prim.get("mode", _GLTF_MODE_TRIANGLES) != _GLTF_MODE_TRIANGLES:
                continue  # strips / fans / points / lines — skip
            idx = prim.get("indices")
            count = None
            if isinstance(idx, int) and 0 <= idx < len(accessors):
                count = accessors[idx].get("count")
            else:
                pos = (prim.get("attributes") or {}).get("POSITION")
                if isinstance(pos, int) and 0 <= pos < len(accessors):
                    count = accessors[pos].get("count")
            if isinstance(count, int):
                total += count // 3
    return total


def resolve_source(context, source_mode, file_path, max_bytes, max_triangles=None):
    """Resolve a source mesh to (local_glb_path, base_name). MAIN THREAD ONLY.

    Exports the scene selection or validates a .glb on disk, and enforces the
    op's size cap. When max_triangles is set, the triangle count is checked
    FIRST (the evaluated selection for an OBJECT source, the parsed GLB for a
    FILE source) and a too-dense mesh is rejected up front. This mirrors the
    web platform, which blocks oversized meshes client-side: without it, a
    dense mesh uploads fine, is accepted by the job queue, then fails at the
    upstream (Tencent) stage with a generic internal error and a credit
    refund. Raises ValueError with a user-facing message."""
    if source_mode == "OBJECT":
        # The glTF exporter (and a clean object-level selection / evaluated
        # mesh) require Object Mode. Drop out of Edit/Sculpt first, or the
        # export fails with a confusing generic error and the cap is checked
        # against the wrong selection.
        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                raise ValueError("Switch to Object Mode, then try again.")
        if max_triangles:
            tris = count_selection_triangles(context)
            if tris > max_triangles:
                raise ValueError(
                    f"This mesh has about {tris:,} triangles, over the "
                    f"{max_triangles:,} limit for this operation. Run Smart "
                    f"Retopology on it first to reduce the polygon count, "
                    f"then try again."
                )
        path, name = export_selection_to_glb(context)
    else:
        raw = (file_path or "").strip()
        if not raw:
            raise ValueError("Choose a .glb file.")
        path = bpy.path.abspath(raw)
        if not os.path.isfile(path):
            raise ValueError("File not found.")
        if not path.lower().endswith(".glb"):
            raise ValueError("Pick a .glb file, or use 'Selected object' for other meshes.")
        name = os.path.splitext(os.path.basename(path))[0]
        if max_triangles:
            tris = count_glb_triangles(path)
            if tris is not None and tris > max_triangles:
                raise ValueError(
                    f"This file has about {tris:,} triangles, over the "
                    f"{max_triangles:,} limit for this operation. Retopologize "
                    f"it first, then try again."
                )
    try:
        size = os.path.getsize(path)
    except OSError:
        raise ValueError("Could not read the mesh file.")
    if size > max_bytes:
        raise ValueError(f"Mesh is larger than {max_bytes // (1024 * 1024)} MB.")
    return path, name


def selected_mesh_label(context):
    """Panel helper: a label for the current selection, or '' if none."""
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if not meshes:
        return ""
    active = context.active_object
    primary = active if (active and active in meshes) else meshes[0]
    label = primary.name
    if len(meshes) > 1:
        label += f"  (+{len(meshes) - 1})"
    return label


# ── result extraction ────────────────────────────────────────────────


def _result_urls(download_urls, import_mode):
    obj_files = (download_urls or {}).get("objFiles", {}) or {}
    if import_mode == "parts":
        parts = []
        for key, url in obj_files.items():
            if key.startswith("part_") and url:
                try:
                    idx = int(key.split("_", 1)[1])
                except ValueError:
                    idx = 0
                parts.append((idx, url))
        if parts:
            parts.sort(key=lambda p: p[0])
            return [u for _, u in parts]
        # Fall back to the single glb the backend also mirrors part_0 to.
        glb = obj_files.get("glb")
        return [glb] if glb else []
    glb = obj_files.get("glb")
    return [glb] if glb else []


# ── pipeline ──────────────────────────────────────────────────────────


def run(*, source_path, upload_name, title, body, import_mode,
        processing_text, done_text, set_status, finish):
    """Spawn the worker. The caller has already set its busy stage.

    body          — the /alpha-5/create body WITHOUT modelUrl (filled here).
    import_mode   — 'single' | 'parts'.
    processing_text / done_text — op-specific status + notice strings.
    set_status(text) / finish(text) — MAIN-THREAD-SAFE callbacks; this module
                  marshals them, so they may touch bpy props directly.
    """

    def status_async(text):
        mainthread.run_on_main_thread(lambda t=text: set_status(t))

    def finish_async(text):
        mainthread.run_on_main_thread(lambda t=text: finish(t))

    def _import(paths):
        # MAIN THREAD (marshalled). Bail if the addon was torn down between
        # enqueue and drain, so a stale task can't import into a fresh session.
        if not _alive:
            return
        try:
            if import_mode == "parts":
                # Segmentation: group the N parts under one parent Empty so they
                # read as a single model with parts (like the web viewer).
                imported = sceneimport.import_parts_under_parent(paths, title)
            else:
                imported = 0
                for p in paths:
                    mainthread.run_in_view3d_context(
                        lambda p=p: bpy.ops.import_scene.gltf(filepath=p)
                    )
                    imported += 1
        except Exception as exc:  # noqa: BLE001
            finish(f"Import failed: {exc!r}")
            return
        if imported == 0:
            finish("Nothing was imported.")
            return
        finish(done_text)
        notice.show(done_text)

    def _poll(post_id):
        deadline = time.time() + _POLL_TIMEOUT_SECONDS
        while time.time() < deadline:
            if not _alive:
                raise ApiError(0, "Cancelled.")
            res = endpoints.poll_generation(post_id) or {}
            status = ((res.get("data", {}) or {}).get("post", {}) or {}).get("status")
            if status == "completed":
                detail = endpoints.get_post(post_id) or {}
                dl = (detail.get("data", {}) or {}).get("downloadUrls", {}) or {}
                urls = _result_urls(dl, import_mode)
                if not urls:
                    raise ApiError(0, "Job finished but no mesh was returned.")
                return urls
            if status == "error":
                raise ApiError(0, "The job failed on the server.")
            status_async(processing_text)
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise _JobStillRunning()

    def worker():
        try:
            # 1. Reserve a Spaces key + presigned PUT (upload-type post).
            status_async("Uploading mesh...")
            created = endpoints.create_upload(upload_name, GLB_CONTENT_TYPE, title) or {}
            data = created.get("data", {}) or {}
            upload_url = data.get("uploadUrl")
            key = (data.get("post", {}) or {}).get("texturedMeshUrl")
            if not upload_url or not key:
                raise ApiError(0, "Could not reserve an upload slot.")

            # 2. PUT the mesh bytes (no auth; content-type matches presign).
            endpoints.upload_to_presigned(upload_url, source_path, GLB_CONTENT_TYPE)

            # 3. Submit the job (modelUrl = the uploaded key).
            status_async("Submitting to Alpha3D...")
            submit_body = dict(body)
            submit_body["modelUrl"] = key
            submitted = endpoints.submit_generation(submit_body) or {}
            post_id = (submitted.get("data", {}) or {}).get("post", {}).get("id")
            if not post_id:
                raise ApiError(0, "Submit did not return a post id.")

            # Surface the new job in the Library immediately with its status.
            mainthread.run_on_main_thread(library.request_refresh)

            # 4. Poll to completion.
            status_async(processing_text)
            urls = _poll(post_id)

            # 5. Download every result mesh + import.
            status_async("Downloading result...")
            paths = []
            for i, url in enumerate(urls):
                dest = os.path.join(
                    tempfile.gettempdir(), f"alpha3d_job_{post_id}_{i}.glb"
                )
                endpoints.download_file(url, dest)
                trimmed, declared, actual = glbutil.sanitize_glb(dest)
                print(
                    f"[Alpha3D] result part {i}: declared={declared} "
                    f"actual={actual} trimmed={trimmed}"
                )
                paths.append(dest)
            if not _alive:
                return
            mainthread.run_on_main_thread(lambda p=paths: _import(p))
        except _JobStillRunning:
            # Submitted and still processing — not an error. The Library tracks
            # it live; the user imports the result from there when it's done.
            finish_async(
                "Still processing — open the Library tab to import it when ready."
            )
        except ApiError as exc:
            finish_async(f"Error: {exc.message}")
        except Exception as exc:  # noqa: BLE001
            finish_async(f"Error: {exc!r}")

    threading.Thread(target=worker, daemon=True, name="Alpha3D-meshjob").start()


def register():
    global _alive
    _alive = True


def unregister():
    global _alive
    _alive = False
