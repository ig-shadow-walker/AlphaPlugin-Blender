"""Smart Retopology tab — rebuild a mesh with cleaner topology.

Source is either the mesh selected in the scene or a .glb on disk; the user
picks a detail level (High/Medium/Low) and polygon type (triangle/quad),
the same controls the platform exposes. Logic lives in
operators/retopology.py.
"""

import bpy

from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE

_CREDIT_COST = 60


class ALPHA3D_PT_retopology(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_retopology"
    bl_label = "Smart Retopology"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        connected = is_connected()
        props = context.window_manager.alpha3d
        busy = props.retopo_stage == "PROCESSING"

        if not connected:
            layout.label(text="Connect your account to retopologize.", icon="INFO")

        col = layout.column()
        col.enabled = connected and not busy

        col.label(text="Source")
        col.prop(props, "retopo_source", expand=True)
        if props.retopo_source == "OBJECT":
            sel = [o for o in context.selected_objects if o.type == "MESH"]
            if sel:
                active = context.active_object
                primary = active if (active and active in sel) else sel[0]
                label = primary.name
                if len(sel) > 1:
                    label += f"  (+{len(sel) - 1})"
                col.label(text=label, icon="OUTLINER_OB_MESH")
            else:
                col.label(text="Select a mesh in the scene", icon="ERROR")
        else:
            col.prop(props, "retopo_file_path", text="GLB")

        col.separator()
        col.prop(props, "retopo_detail")
        col.label(text="Polygon type")
        col.prop(props, "retopo_poly_type", expand=True)

        layout.label(text=f"Uses {_CREDIT_COST} 3D credits", icon="FUND")

        run = layout.column()
        run.enabled = connected and not busy
        run.operator("alpha3d.retopologize", text="Retopologize", icon="MOD_REMESH")

        if busy:
            layout.label(text=props.retopo_status or "Working...", icon="SORTTIME")
        elif props.retopo_status:
            layout.label(text=props.retopo_status, icon="INFO")


classes = (ALPHA3D_PT_retopology,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
