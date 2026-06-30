"""Tools tab — Alpha3D pipeline tools.

Text / Image to 3D mirrors the web app's GenerationBox: pick a quality tier
(the same 3 levels the website has), see the credit cost, and for a text
prompt review the generated image (Regenerate / Create 3D) before committing
to the 3D job. The remaining pipeline tools are coming-soon stubs.
"""

import bpy

from ..constants import TOOLS, credit_cost
from ..operators import generate as gen_ops
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
        stage = props.gen_stage
        busy = stage in {"IMAGING", "GENERATING"}

        box = layout.box()
        box.label(text="Text / Image to 3D", icon="MESH_MONKEY")

        if not connected:
            box.label(text="Connect your account to generate.", icon="INFO")

        # ── Quality settings (always visible, locked while a job runs) ──
        settings = box.column(align=True)
        settings.enabled = connected and not busy
        settings.label(text="Quality")
        settings.prop(props, "gen_quality", text="")

        is_low = props.gen_quality == "LOW_POLY"
        if is_low:
            settings.prop(props, "gen_poly_type", expand=True)
        pbr_row = settings.row()
        pbr_row.enabled = not is_low
        pbr_row.prop(props, "gen_enable_pbr")
        settings.prop(props, "gen_face_count")

        cost = credit_cost(props.gen_quality, props.gen_enable_pbr)
        box.label(text=f"Uses {cost} 3D credits", icon="FUND")

        # ── Stage-specific body ──────────────────────────────────────
        if stage == "PREVIEW":
            icon_id = gen_ops.get_preview_icon_id()
            if icon_id:
                box.template_icon(icon_value=icon_id, scale=8.0)
            box.label(text="Happy with this image?")
            row = box.row(align=True)
            row.operator("alpha3d.regenerate_image", text="Regenerate", icon="FILE_REFRESH")
            row.operator("alpha3d.create_3d", text="Create 3D", icon="MESH_MONKEY")
            box.operator("alpha3d.discard_preview", text="Discard", icon="X")
        elif busy:
            box.label(text=props.gen_status or "Working...", icon="SORTTIME")
        else:  # IDLE
            col = box.column()
            col.enabled = connected
            col.label(text="Describe a model, or pick a reference image:")
            col.prop(props, "gen_prompt", text="")
            col.prop(props, "gen_image_path", text="Image")

            if (props.gen_image_path or "").strip():
                label, icon = "Generate 3D", "PLAY"
            elif (props.gen_prompt or "").strip():
                label, icon = "Generate Image", "IMAGE_DATA"
            else:
                label, icon = "Generate", "PLAY"
            col.operator("alpha3d.generate", text=label, icon=icon)

            if props.gen_status:
                box.label(text=props.gen_status, icon="INFO")

        # ── Remaining pipeline tools (coming soon) ───────────────────
        # Every id below has its own dedicated panel now (in-plugin or a
        # web link-out: uv_unwrap, texture, tag_asset open the web app), so
        # nothing currently renders here — the loop stays as a backstop for
        # any future stub added to TOOLS.
        live = {
            "generate_3d", "retopology", "uv_unwrap", "texture",
            "segmentation", "rigging", "tag_asset",
        }
        col = layout.column(align=True)
        col.enabled = connected
        for tool in TOOLS:
            if tool["id"] in live:
                continue
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
