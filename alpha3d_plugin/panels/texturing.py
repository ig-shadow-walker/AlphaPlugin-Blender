"""AI Texturing tab — opens the web app's AI texturing tool.

AI texturing is run on the web app, not from inside Blender: the flow needs a
text/style prompt plus a preview-and-accept step, and (like UV unwrap) the
texturing pipeline works against your generation's ORIGINAL mesh, which the
web app submits by reference. This panel links out to /ai-texturing, where the
user picks a generation and textures it.
"""

import bpy

from ..preferences import get_prefs
from .main import CATEGORY, REGION, SPACE

_WEB_PATH = "/ai-texturing"
_FALLBACK_WEB_BASE = "https://alpha3d.io"


def _texturing_url():
    """Web app AI-texturing URL, honoring the configured web host."""
    try:
        base = (get_prefs().web_base_url or "").strip()
    except (KeyError, AttributeError):
        base = ""
    base = (base or _FALLBACK_WEB_BASE).rstrip("/")
    return base + _WEB_PATH


class ALPHA3D_PT_texturing(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_texturing"
    bl_label = "AI Texturing"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="AI texturing runs on the web app,")
        col.label(text="on your model's original mesh.")
        op = layout.operator(
            "wm.url_open", text="Open AI Texturing on Alpha3D", icon="URL"
        )
        op.url = _texturing_url()


classes = (ALPHA3D_PT_texturing,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
