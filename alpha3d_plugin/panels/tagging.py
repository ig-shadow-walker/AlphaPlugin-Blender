"""Asset Tagging tab — opens the web app's asset tagging tool.

Asset tagging photographs a model from several angles and runs vision tagging
to make your 3D library searchable. It operates on your saved library on the
web app, so this panel links out to /asset-tagging rather than tagging from
inside Blender.
"""

import bpy

from ..preferences import get_prefs
from .main import CATEGORY, REGION, SPACE

_WEB_PATH = "/asset-tagging"
_FALLBACK_WEB_BASE = "https://alpha3d.io"


def _tagging_url():
    """Web app asset-tagging URL, honoring the configured web host."""
    try:
        base = (get_prefs().web_base_url or "").strip()
    except (KeyError, AttributeError):
        base = ""
    base = (base or _FALLBACK_WEB_BASE).rstrip("/")
    return base + _WEB_PATH


class ALPHA3D_PT_tagging(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_tagging"
    bl_label = "Asset Tagging"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 9
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="Tag and search your 3D library")
        col.label(text="on the web app.")
        op = layout.operator(
            "wm.url_open", text="Open Asset Tagging on Alpha3D", icon="URL"
        )
        op.url = _tagging_url()


classes = (ALPHA3D_PT_tagging,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
