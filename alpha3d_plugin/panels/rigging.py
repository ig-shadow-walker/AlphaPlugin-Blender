"""AI Rigging tab — auto-rig a humanoid T-pose mesh.

Source is either the mesh selected in the scene or a .glb on disk. Best on a
humanoid character in a standard T-pose (Tencent's auto-rigging requirement).
Before the paid submit, a scene-object source gets an advisory Claude-vision
T-pose pre-check; a bad pose shows a warning + "Rig anyway". Logic lives in
operators/rigging.py.
"""

import textwrap

import bpy

from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE

_CREDIT_COST = 27


class ALPHA3D_PT_rigging(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_rigging"
    bl_label = "AI Rigging"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 6
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        connected = is_connected()
        props = context.window_manager.alpha3d
        stage = props.rig_stage

        if not connected:
            layout.label(text="Connect your account to rig.", icon="INFO")

        # Pose pre-check came back questionable — let the user decide.
        if stage == "POSE_WARN":
            box = layout.box()
            box.label(text="Pose check", icon="ERROR")
            for line in textwrap.wrap(props.rig_pose_warning or "", width=34):
                box.label(text=line)
            row = box.row(align=True)
            row.operator("alpha3d.rig_confirm", text="Rig anyway", icon="ARMATURE_DATA")
            row.operator("alpha3d.rig_cancel", text="Cancel", icon="X")
            return

        busy = stage in {"PROCESSING", "CHECKING"}

        col = layout.column()
        col.enabled = connected and not busy

        col.label(text="Source")
        col.prop(props, "rig_source", expand=True)
        if props.rig_source == "OBJECT":
            sel = [o for o in context.selected_objects if o.type == "MESH"]
            non_mesh = [o for o in context.selected_objects if o.type != "MESH"]
            if sel:
                active = context.active_object
                primary = active if (active and active in sel) else sel[0]
                label = primary.name
                if len(sel) > 1:
                    label += f"  (+{len(sel) - 1})"
                col.label(text=label, icon="OUTLINER_OB_MESH")
                if non_mesh:
                    col.label(
                        text="Only the mesh is sent; armatures are ignored.",
                        icon="INFO",
                    )
            else:
                col.label(text="Select a mesh in the scene", icon="ERROR")
        else:
            col.prop(props, "rig_file_path", text="GLB")

        layout.label(text="Best on a humanoid in a T-pose.", icon="OUTLINER_OB_ARMATURE")
        layout.label(text=f"Uses {_CREDIT_COST} 3D credits", icon="FUND")

        run = layout.column()
        run.enabled = connected and not busy
        run.operator("alpha3d.rig", text="Rig", icon="ARMATURE_DATA")

        if busy:
            layout.label(text=props.rig_status or "Working...", icon="SORTTIME")
        elif props.rig_status:
            layout.label(text=props.rig_status, icon="INFO")


classes = (ALPHA3D_PT_rigging,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
