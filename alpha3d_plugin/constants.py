"""Shared constants for the Alpha3D Blender add-on.

`ADDON_ID` is the key Blender uses for this add-on in
`bpy.context.preferences.addons[...]`. It resolves to the top-level
package name (`alpha3d_plugin`) regardless of which submodule imports
it, so helpers in `api/`, `auth/`, etc. can all find the preferences.
"""

# `__package__` inside this module is the package that contains it:
# `alpha3d_plugin`. That is exactly the add-on id Blender registers.
ADDON_ID = __package__

# API host (NestJS backend). Overridable per-install in the add-on
# preferences so we can point at staging / localhost during dev.
# NOTE: currently set to the LOCAL dev backend (port 4000). Restore to
# "https://api.alpha3d.io" before packaging for release.
DEFAULT_BASE_URL = "http://localhost:4000"

# Web app host — where the browser-loopback login page lives
# (`/plugin-auth?port=<loopback-port>`).
# NOTE: currently set to the LOCAL dev frontend (port 3000). Restore to
# "https://alpha3d.io" before packaging for release.
DEFAULT_WEB_BASE_URL = "http://localhost:3000"

# How long the loopback listener waits for the browser to hand back a
# token before giving up (seconds).
LOGIN_TIMEOUT_SECONDS = 180

# Curated Alpha3D tools surfaced in the Tools tab. Each entry is a stub
# in Phase 0 — wired to real endpoints in later phases. `id` is passed
# to the generic `alpha3d.run_tool` operator.
TOOLS = (
    {"id": "generate_3d", "label": "Text / Image to 3D", "icon": "MESH_MONKEY"},
    {"id": "retopology", "label": "Smart Topology", "icon": "MOD_REMESH"},
    {"id": "uv_unwrap", "label": "UV Unwrap", "icon": "UV"},
    {"id": "texture", "label": "AI Texture", "icon": "TEXTURE"},
    {"id": "rigging", "label": "Auto Rig", "icon": "ARMATURE_DATA"},
    {"id": "segmentation", "label": "Segment Parts", "icon": "MOD_EXPLODE"},
    {"id": "convert", "label": "Convert Format", "icon": "FILE_REFRESH"},
    {"id": "tag_asset", "label": "Tag Asset", "icon": "BOOKMARKS"},
)
