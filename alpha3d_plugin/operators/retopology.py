"""Smart Retopology — rebuild a mesh with cleaner topology.

Source is the selected scene object (exported to GLB) or a .glb on disk; the
user picks a detail level (octree 1/2/3) and polygon type. The shared mesh
pipeline (operators/meshjob.py) does upload -> submit -> poll -> import.
60 credits.
"""

import bpy

from . import meshjob
from .. import mainthread
from ..preferences import is_connected

# Backend caps the source mesh at 200 MB.
_MAX_BYTES = 200 * 1024 * 1024
# Detail level -> Hunyuan octreeResolution (the platform's High/Medium/Low).
_DETAIL_OCTREE = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _set_status(text):
    props = _props()
    if props:
        props.retopo_status = text
    mainthread.tag_redraw_all()


def _finish(text):
    props = _props()
    if props:
        props.retopo_stage = "IDLE"
        props.retopo_status = text
    mainthread.tag_redraw_all()


class ALPHA3D_OT_retopologize(bpy.types.Operator):
    bl_idname = "alpha3d.retopologize"
    bl_label = "Retopologize"
    bl_description = (
        "Rebuild the mesh with cleaner edge flow and controlled density "
        "(Smart Retopology). Costs 60 credits"
    )

    def execute(self, context):
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.retopo_stage == "PROCESSING":
            self.report({"WARNING"}, "A retopology job is already running.")
            return {"CANCELLED"}

        try:
            src, name = meshjob.resolve_source(
                context, props.retopo_source, props.retopo_file_path, _MAX_BYTES
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        body = {
            "generationType": "alpha-5-retopology",
            "file3dType": "GLB",
            "octreeResolution": _DETAIL_OCTREE.get(props.retopo_detail, 3),
            "polygonType": "quadrilateral" if props.retopo_poly_type == "QUAD" else "triangle",
            "postTitle": f"Retopologize - {name}"[:100],
            "availability": "in_review",
            "origin": "blender",
        }
        props.retopo_stage = "PROCESSING"
        props.retopo_status = "Uploading mesh..."
        meshjob.run(
            source_path=src,
            upload_name=f"{name}.glb",
            title=body["postTitle"],
            body=body,
            import_mode="single",
            processing_text="Retopologizing your mesh...",
            done_text="Retopology complete.",
            set_status=_set_status,
            finish=_finish,
        )
        return {"FINISHED"}


classes = (ALPHA3D_OT_retopologize,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
