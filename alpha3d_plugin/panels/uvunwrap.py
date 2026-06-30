"""UV Unwrap tab — opens the web app's UV unwrapping tool.

UV unwrap is intentionally NOT run from inside Blender: Tencent's UV solver
fails on a GLB re-exported by Blender's glTF exporter, while it succeeds on
its own pipeline's GLB (which the web app submits by reference). Rather than
fight that exporter mismatch, this panel links out to /uv-unwrapping, where
the user picks a generation and unwraps it against the original mesh.
"""

import bpy

from ..preferences import get_prefs
from .main import CATEGORY, REGION, SPACE

_WEB_PATH = "/uv-unwrapping"
_FALLBACK_WEB_BASE = "https://alpha3d.io"


def _uv_unwrap_url():
    """Web app UV-unwrap URL, honoring the configured web host."""
    try:
        base = (get_prefs().web_base_url or "").strip()
    except (KeyError, AttributeError):
        base = ""
    base = (base or _FALLBACK_WEB_BASE).rstrip("/")
    return base + _WEB_PATH


class ALPHA3D_PT_uv_unwrap(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_uv_unwrap"
    bl_label = "UV Unwrap"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="UV unwrapping runs on the web app,")
        col.label(text="on your model's original mesh.")
        op = layout.operator(
            "wm.url_open", text="Open UV Unwrap on Alpha3D", icon="URL"
        )
        op.url = _uv_unwrap_url()


classes = (ALPHA3D_PT_uv_unwrap,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
