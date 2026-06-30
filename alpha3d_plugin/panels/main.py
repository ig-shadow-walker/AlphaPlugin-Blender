"""Connection header panel — top of the Alpha3D sidebar tab."""

import bpy

from ..operators import notice
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

        # Dismissible notice (e.g. a finished generation). Pinned to the top
        # of the Alpha3D tab so it's visible regardless of which sub-panel
        # is expanded; the X clears it.
        message, icon = notice.current()
        if message:
            banner = layout.box()
            row = banner.row(align=True)
            row.label(text=message, icon=icon)
            close = row.row(align=True)
            close.alignment = "RIGHT"
            close.operator("alpha3d.dismiss_notice", text="", icon="X", emboss=False)

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
