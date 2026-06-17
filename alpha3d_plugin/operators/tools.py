"""Tool operators.

Phase 0: a single generic operator that stands in for every curated
Alpha3D tool. It validates connection + reports which tool was clicked,
so the Tools tab is fully wired end-to-end before the real job calls
land in a later phase.
"""

import bpy
from bpy.props import StringProperty

from ..preferences import is_connected


class ALPHA3D_OT_run_tool(bpy.types.Operator):
    bl_idname = "alpha3d.run_tool"
    bl_label = "Run Alpha3D Tool"
    bl_description = "Run an Alpha3D pipeline tool on the active object"

    tool: StringProperty(default="")
    tool_label: StringProperty(default="")

    def execute(self, context):
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}

        label = self.tool_label or self.tool or "tool"
        # Stub: real implementation (upload active mesh → call the matching
        # alpha-5 endpoint → poll → import result) arrives in a later phase.
        print(f"[Alpha3D] run_tool: {self.tool!r}")
        self.report({"INFO"}, f"{label}: coming soon (Phase 0 stub).")
        return {"FINISHED"}


classes = (ALPHA3D_OT_run_tool,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
