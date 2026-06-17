"""Tools tab — every Alpha3D pipeline tool, individually runnable."""

import bpy

from ..constants import TOOLS
from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE


class ALPHA3D_PT_tools(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_tools"
    bl_label = "Tools"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        layout.enabled = is_connected()

        col = layout.column(align=True)
        for tool in TOOLS:
            op = col.operator(
                "alpha3d.run_tool", text=tool["label"], icon=tool.get("icon", "DOT")
            )
            op.tool = tool["id"]
            op.tool_label = tool["label"]


classes = (ALPHA3D_PT_tools,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
