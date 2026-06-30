"""AI Segmentation tab — split a mesh into its semantic parts.

Source is the selected scene object or a .glb on disk; the part count is
chosen automatically (no controls, matching the platform). Each returned
part imports as its own object. Logic lives in operators/segmentation.py.
"""

import bpy

from ..operators import meshjob
from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE

_CREDIT_COST = 61


class ALPHA3D_PT_segmentation(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_segmentation"
    bl_label = "AI Segmentation"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        connected = is_connected()
        props = context.window_manager.alpha3d
        busy = props.seg_stage == "PROCESSING"

        if not connected:
            layout.label(text="Connect your account to segment models.", icon="INFO")

        col = layout.column()
        col.enabled = connected and not busy
        col.label(text="Source")
        col.prop(props, "seg_source", expand=True)
        if props.seg_source == "OBJECT":
            label = meshjob.selected_mesh_label(context)
            if label:
                col.label(text=label, icon="OUTLINER_OB_MESH")
            else:
                col.label(text="Select a mesh in the scene", icon="ERROR")
        else:
            col.prop(props, "seg_file_path", text="GLB")

        layout.label(text="Parts are detected automatically.", icon="INFO")
        layout.label(text=f"Uses {_CREDIT_COST} 3D credits", icon="FUND")

        run = layout.column()
        run.enabled = connected and not busy
        run.operator("alpha3d.segment", text="Segment", icon="MOD_EXPLODE")

        if busy:
            layout.label(text=props.seg_status or "Working...", icon="SORTTIME")
        elif props.seg_status:
            layout.label(text=props.seg_status, icon="INFO")


classes = (ALPHA3D_PT_segmentation,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
