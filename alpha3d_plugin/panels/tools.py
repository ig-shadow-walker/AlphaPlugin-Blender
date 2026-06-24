"""Tools tab — Alpha3D pipeline tools.

Text / Image to 3D is live: it generates a model from a prompt or a
reference image and imports it into the scene. The rest are stubs that
report "coming soon" until later phases wire them up.
"""

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
        connected = is_connected()
        props = context.window_manager.alpha3d

        # ── Text / Image to 3D (live) ────────────────────────────────
        box = layout.box()
        box.label(text="Text / Image to 3D", icon="MESH_MONKEY")

        col = box.column()
        col.enabled = connected and not props.gen_is_running
        col.label(text="Describe a model, or pick a reference image:")
        col.prop(props, "gen_prompt", text="")
        col.prop(props, "gen_image_path", text="Image")
        col.prop(props, "gen_enable_pbr")
        col.operator("alpha3d.generate_3d", text="Generate", icon="PLAY")

        if props.gen_is_running:
            box.label(text=props.gen_status or "Working…", icon="SORTTIME")
        elif props.gen_status:
            box.label(text=props.gen_status, icon="INFO")

        # ── Remaining pipeline tools (coming soon) ───────────────────
        col = layout.column(align=True)
        col.enabled = connected
        for tool in TOOLS:
            if tool["id"] == "generate_3d":
                continue  # handled by the live section above
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
