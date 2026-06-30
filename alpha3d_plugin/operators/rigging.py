"""AI Rigging — auto-rig a humanoid T-pose mesh.

Source is the selected scene object (exported to GLB) or a .glb on disk.
Tencent SubmitAutoRiggingJob expects a humanoid in a standard T-pose; a GLB
input is converted to FBX server-side. v1 is rig-only (an armature + skin
weights, no preset animation). The shared mesh pipeline (operators/meshjob.py)
does upload -> submit -> poll -> import; the result is a single rigged GLB
(armature + skinned mesh) imported via import_mode 'single'. 27 credits
(GLB input includes the server-side GLB->FBX convert).

Advisory T-pose pre-check (scene-object source only): before the paid submit,
front + side ortho views of the mesh are rendered and sent to the web app's
Claude-vision validator. If it's not a humanoid T-pose the panel warns and
offers "Rig anyway"; a good pose (or any render/validation failure) proceeds
straight to rigging — the check NEVER blocks.

State machine (rig_stage): IDLE -> CHECKING -> (POSE_WARN ->) PROCESSING.
"""

import base64
import os
import tempfile
import threading

import bpy
import mathutils

from . import meshjob
from .. import mainthread
from ..api import endpoints
from ..preferences import is_connected

# Tencent caps the FBX actually sent to auto-rigging at 50 MB.
_MAX_BYTES = 50 * 1024 * 1024

# Mesh resolved + exported for a pose that the user must confirm ("Rig anyway").
_pending_rig = {}

# Cleared on unregister so a pose-check daemon that outlives a reload can't
# resume into a paid submit after re-register.
_alive = True


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _set_status(text):
    props = _props()
    if props:
        props.rig_status = text
    mainthread.tag_redraw_all()


def _finish(text):
    props = _props()
    if props:
        props.rig_stage = "IDLE"
        props.rig_status = text
        props.rig_pose_warning = ""
    mainthread.tag_redraw_all()


def _primary_mesh(context):
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if not meshes:
        return None
    active = context.active_object
    return active if (active and active in meshes) else meshes[0]


# ── advisory T-pose pre-check ─────────────────────────────────────────


def _render_pose_views(context, obj):
    """Render front + side ortho views of `obj` to PNG, returned as
    [{mediaType, data(base64)}]. MAIN THREAD ONLY. Returns [] on ANY failure —
    the pre-check is advisory and must never block rigging.

    Renders in a throwaway scene (Workbench, transparent film) containing only
    the target mesh + an ortho camera, so nothing else in the user's scene is
    drawn and the user's scene/view is untouched."""
    scene = None
    cam = None
    cam_data = None
    win = context.window
    prev_scene = win.scene if win else None
    try:
        scene = bpy.data.scenes.new("alpha3d_pose_check")
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.film_transparent = True
        scene.render.resolution_x = 640
        scene.render.resolution_y = 640
        scene.render.image_settings.file_format = "PNG"
        scene.collection.objects.link(obj)

        cam_data = bpy.data.cameras.new("alpha3d_pose_cam")
        cam_data.type = "ORTHO"
        cam = bpy.data.objects.new("alpha3d_pose_cam", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam

        corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        xs = [v.x for v in corners]
        ys = [v.y for v in corners]
        zs = [v.z for v in corners]
        center = mathutils.Vector((
            (min(xs) + max(xs)) / 2,
            (min(ys) + max(ys)) / 2,
            (min(zs) + max(zs)) / 2,
        ))
        dx, dy, dz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
        span = max(dx, dy, dz, 0.01)

        # (camera offset from center, in-plane size for ortho_scale)
        views = (
            (mathutils.Vector((0.0, -(dy + span + 1.0), 0.0)), max(dx, dz)),  # front
            (mathutils.Vector((dx + span + 1.0, 0.0, 0.0)), max(dy, dz)),     # side
        )
        out = []
        for offset, plane in views:
            cam.location = center + offset
            cam.rotation_euler = (
                (center - cam.location).to_track_quat("-Z", "Y").to_euler()
            )
            cam_data.ortho_scale = max(plane, 0.01) * 1.2

            fd, path = tempfile.mkstemp(suffix=".png", prefix="alpha3d_pose_")
            os.close(fd)
            scene.render.filepath = path
            if win:
                win.scene = scene
            try:
                bpy.ops.render.render(write_still=True)
            finally:
                if win:
                    win.scene = prev_scene
            try:
                with open(path, "rb") as f:
                    out.append({
                        "mediaType": "image/png",
                        "data": base64.b64encode(f.read()).decode("ascii"),
                    })
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return out
    except Exception as exc:  # noqa: BLE001 — advisory; never block rigging
        print(f"[Alpha3D] pose-check render failed: {exc!r}")
        return []
    finally:
        # Never remove a scene a window is still displaying — repoint every
        # window off the throwaway scene first (removing a window's active
        # scene can crash Blender). Only remove once nothing references it.
        try:
            if scene is not None:
                wm = bpy.context.window_manager
                windows = list(wm.windows) if wm else []
                # Fall back to any other scene so the throwaway is never the
                # one a window keeps displaying (prev_scene is effectively
                # always set, but don't rely on it).
                fallback = prev_scene or next(
                    (s for s in bpy.data.scenes if s is not scene), None
                )
                for w in windows:
                    if w.scene is scene and fallback is not None:
                        w.scene = fallback
                if not any(w.scene is scene for w in windows):
                    bpy.data.scenes.remove(scene)
        except Exception:  # noqa: BLE001
            pass
        try:
            if cam is not None and cam.name in bpy.data.objects:
                bpy.data.objects.remove(cam, do_unlink=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            if cam_data is not None and cam_data.name in bpy.data.cameras:
                bpy.data.cameras.remove(cam_data)
        except Exception:  # noqa: BLE001
            pass


def _resume_check(decision):
    """Main thread: run the pose-check's decision (rig or warn) ONLY if this
    check is still the active one. A reload (or teardown) resets rig_stage to
    IDLE and clears _alive, orphaning the daemon that scheduled us — in that
    case do nothing, so a stale check can never trigger an unbidden submit."""
    props = _props()
    if not _alive or not props or props.rig_stage != "CHECKING":
        return
    decision()


def _validate_worker(frames, src, name):
    """Worker: ask the web app's vision validator about the pose, then either
    rig (good pose, or any failure — advisory) or warn (bad pose). The decision
    is gated on the main thread by _resume_check so a reload can't resurrect
    a dead check into a paid submit."""
    try:
        res = endpoints.validate_rigging_pose(frames) or {}
        data = res.get("data", {}) or {}
        if data.get("isTPose"):
            mainthread.run_on_main_thread(
                lambda s=src, n=name: _resume_check(lambda: _start_rig(s, n))
            )
        else:
            reason = str(data.get("reason") or "")
            mainthread.run_on_main_thread(
                lambda r=reason, s=src, n=name: _resume_check(
                    lambda: _pose_warn(r, s, n)
                )
            )
    except Exception as exc:  # noqa: BLE001 — advisory; proceed on check failure
        print(f"[Alpha3D] pose check failed: {exc!r}")
        mainthread.run_on_main_thread(
            lambda s=src, n=name: _resume_check(lambda: _start_rig(s, n))
        )


def _pose_warn(reason, src, name):
    """Main thread: the pose looks off — hold for the user to confirm."""
    global _pending_rig
    _pending_rig = {"src": src, "name": name}
    props = _props()
    if props:
        props.rig_stage = "POSE_WARN"
        props.rig_status = ""
        props.rig_pose_warning = (
            reason or "This may not be a humanoid in a T-pose; rigging may fail."
        )
    mainthread.tag_redraw_all()


# ── submit ─────────────────────────────────────────────────────────────


def _start_rig(src, name):
    """Main thread: hand the (already-exported) mesh to the rigging pipeline."""
    body = {
        "generationType": "alpha-5-rigging",
        "file3dType": "GLB",
        "postTitle": f"Rig - {name}"[:100],
        "availability": "in_review",
        "origin": "blender",
    }
    props = _props()
    if props:
        props.rig_stage = "PROCESSING"
        props.rig_status = "Uploading mesh..."
        props.rig_pose_warning = ""
    mainthread.tag_redraw_all()
    meshjob.run(
        source_path=src,
        upload_name=f"{name}.glb",
        title=body["postTitle"],
        body=body,
        import_mode="single",
        processing_text="Rigging your model...",
        done_text="Rigging complete.",
        set_status=_set_status,
        finish=_finish,
    )


# ── operators ──────────────────────────────────────────────────────────


class ALPHA3D_OT_rig(bpy.types.Operator):
    bl_idname = "alpha3d.rig"
    bl_label = "Rig"
    bl_description = (
        "Auto-rig a humanoid mesh in a T-pose (adds an armature + skin "
        "weights). Costs 27 credits"
    )

    def execute(self, context):
        global _pending_rig
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.rig_stage in {"PROCESSING", "CHECKING"}:
            self.report({"WARNING"}, "A rigging job is already running.")
            return {"CANCELLED"}

        # A fresh run invalidates any pose-warning still pending from before,
        # so a stale "Rig anyway" can never re-submit an old mesh. Also drop a
        # lingering POSE_WARN box (reachable only via the search menu) so an
        # early resolve_source error doesn't leave stale warning UI on screen.
        _pending_rig = {}
        if props.rig_stage == "POSE_WARN":
            props.rig_stage = "IDLE"
            props.rig_pose_warning = ""

        try:
            src, name = meshjob.resolve_source(
                context, props.rig_source, props.rig_file_path, _MAX_BYTES
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Advisory T-pose pre-check — only for a scene object (a .glb on disk
        # isn't in the scene to render). Any render failure falls through to
        # rigging directly.
        if props.rig_source == "OBJECT":
            obj = _primary_mesh(context)
            frames = _render_pose_views(context, obj) if obj else []
            if frames:
                props.rig_stage = "CHECKING"
                props.rig_status = "Checking T-pose..."
                props.rig_pose_warning = ""
                mainthread.tag_redraw_all()
                threading.Thread(
                    target=_validate_worker,
                    args=(frames, src, name),
                    daemon=True,
                    name="Alpha3D-pose",
                ).start()
                return {"FINISHED"}

        _start_rig(src, name)
        return {"FINISHED"}


class ALPHA3D_OT_rig_confirm(bpy.types.Operator):
    bl_idname = "alpha3d.rig_confirm"
    bl_label = "Rig anyway"
    bl_description = "Rig this mesh despite the T-pose warning"

    def execute(self, context):
        global _pending_rig
        # Only valid while a pose warning is on screen; ignore if fired any
        # other way (search menu, script) so it can't bypass the busy guard.
        if context.window_manager.alpha3d.rig_stage != "POSE_WARN":
            return {"CANCELLED"}
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        pend = _pending_rig
        _pending_rig = {}
        if not pend.get("src"):
            self.report({"ERROR"}, "Nothing to rig — run it again.")
            _finish("")
            return {"CANCELLED"}
        _start_rig(pend["src"], pend["name"])
        return {"FINISHED"}


class ALPHA3D_OT_rig_cancel(bpy.types.Operator):
    bl_idname = "alpha3d.rig_cancel"
    bl_label = "Cancel"
    bl_description = "Dismiss the T-pose warning without rigging"

    def execute(self, context):
        global _pending_rig
        # Only meaningful while the pose warning is showing; never let it reset
        # the stage out from under an in-flight CHECKING/PROCESSING job.
        if context.window_manager.alpha3d.rig_stage != "POSE_WARN":
            return {"CANCELLED"}
        _pending_rig = {}
        _finish("")
        return {"FINISHED"}


classes = (ALPHA3D_OT_rig, ALPHA3D_OT_rig_confirm, ALPHA3D_OT_rig_cancel)


def register():
    global _pending_rig, _alive
    _pending_rig = {}
    _alive = True
    for cls in classes:
        bpy.utils.register_class(cls)
    # Clear any transient stage left over from a reload (the daemon worker that
    # would advance it is gone after a reload) so the panel can never be
    # stranded disabled. Props are session-scoped; this is belt-and-suspenders.
    try:
        wm = bpy.context.window_manager
        props = getattr(wm, "alpha3d", None) if wm else None
        if props and props.rig_stage != "IDLE":
            props.rig_stage = "IDLE"
            props.rig_status = ""
            props.rig_pose_warning = ""
    except Exception:  # noqa: BLE001
        pass


def unregister():
    global _pending_rig, _alive
    _alive = False
    _pending_rig = {}
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
