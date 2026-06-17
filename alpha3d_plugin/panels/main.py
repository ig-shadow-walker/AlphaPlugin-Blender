"""Connection header panel — top of the Alpha3D sidebar tab."""

import bpy

from ..preferences import is_connected

# Shared sidebar location for every Alpha3D panel.
SPACE = "VIEW_3D"
REGION = "UI"
CATEGORY = "Alpha3D"


class ALPHA3D_PT_main(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_main"
    bl_label = "Alpha3D"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        props = context.window_manager.alpha3d
        connected = is_connected()

        row = layout.row(align=True)
        if connected:
            row.label(text="Connected", icon="CHECKMARK")
            row.operator("alpha3d.logout", text="", icon="UNLINKED")
        else:
            row.label(text="Not connected", icon="ERROR")
            layout.operator("alpha3d.login", icon="URL")

        if props.status_text:
            layout.label(text=props.status_text, icon="INFO")


classes = (ALPHA3D_PT_main,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
