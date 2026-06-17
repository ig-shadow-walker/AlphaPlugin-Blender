"""Add-on preferences — the only thing that persists across restarts.

Stores the JWT (from the browser-loopback login) and the two host URLs.
The token is the user's standard Alpha3D account token; we keep it here
so a 30-day session survives Blender restarts (Blender writes prefs to
its userpref blend on save).
"""

import bpy
from bpy.props import StringProperty

from .constants import ADDON_ID, DEFAULT_BASE_URL, DEFAULT_WEB_BASE_URL


def get_prefs():
    """Return this add-on's preferences from anywhere in the package."""
    return bpy.context.preferences.addons[ADDON_ID].preferences


def is_connected() -> bool:
    try:
        return bool(get_prefs().token)
    except (KeyError, AttributeError):
        return False


class Alpha3DAddonPreferences(bpy.types.AddonPreferences):
    # Must equal the registered add-on package name.
    bl_idname = ADDON_ID

    token: StringProperty(
        name="Account Token",
        description="Your Alpha3D session token. Set automatically when you log in",
        default="",
        subtype="PASSWORD",
    )

    base_url: StringProperty(
        name="API URL",
        description="Alpha3D API host. Change only for staging / local development",
        default=DEFAULT_BASE_URL,
    )

    web_base_url: StringProperty(
        name="Web URL",
        description="Alpha3D web app host (used for browser login)",
        default=DEFAULT_WEB_BASE_URL,
    )

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        if is_connected():
            row = box.row()
            row.label(text="Connected to your Alpha3D account.", icon="CHECKMARK")
            box.operator("alpha3d.logout", icon="UNLINKED")
        else:
            row = box.row()
            row.label(text="Not connected.", icon="ERROR")
            box.operator("alpha3d.login", icon="URL")

        col = layout.column()
        col.use_property_split = True
        col.prop(self, "base_url")
        col.prop(self, "web_base_url")


classes = (Alpha3DAddonPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
