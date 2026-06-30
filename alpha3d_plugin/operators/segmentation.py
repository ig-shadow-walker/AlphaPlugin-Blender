"""AI Segmentation — split a mesh into its semantic parts.

Source is the selected scene object (exported to GLB) or a .glb on disk.
One-shot auto-segmentation (the live platform path — no parts-count control
and no staged vertex editing; Tencent decides the number of parts). The
shared mesh pipeline (operators/meshjob.py) does upload -> submit -> poll,
then imports EACH returned part as its own object. 61 credits (a GLB input
is auto-converted to FBX server-side). 55 MB source cap.
"""

import bpy

from . import meshjob
from .. import mainthread
from ..preferences import is_connected

# Segmentation's source cap is stricter than retopology/UV (55 MB, not 200).
_MAX_BYTES = 55 * 1024 * 1024


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _set_status(text):
    props = _props()
    if props:
        props.seg_status = text
    mainthread.tag_redraw_all()


def _finish(text):
    props = _props()
    if props:
        props.seg_stage = "IDLE"
        props.seg_status = text
    mainthread.tag_redraw_all()


class ALPHA3D_OT_segment(bpy.types.Operator):
    bl_idname = "alpha3d.segment"
    bl_label = "Segment"
    bl_description = (
        "Split the mesh into its semantic parts (AI Segmentation). "
        "Costs 61 credits"
    )

    def execute(self, context):
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.seg_stage == "PROCESSING":
            self.report({"WARNING"}, "A segmentation job is already running.")
            return {"CANCELLED"}

        try:
            src, name = meshjob.resolve_source(
                context, props.seg_source, props.seg_file_path, _MAX_BYTES
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # One-shot auto-segmentation: omit enableStagedGeneration /
        # partSegmentationInfo (the live web path). Tencent returns N parts.
        body = {
            "generationType": "alpha-5-segment",
            "file3dType": "GLB",
            "postTitle": f"Segment - {name}"[:100],
            "availability": "in_review",
            "origin": "blender",
        }
        props.seg_stage = "PROCESSING"
        props.seg_status = "Uploading mesh..."
        meshjob.run(
            source_path=src,
            upload_name=f"{name}.glb",
            title=body["postTitle"],
            body=body,
            import_mode="parts",
            processing_text="Segmenting your model...",
            done_text="Segmentation complete.",
            set_status=_set_status,
            finish=_finish,
        )
        return {"FINISHED"}


classes = (ALPHA3D_OT_segment,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
