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
# Production = the DigitalOcean app host. For LOCAL dev point this at
# "http://localhost:4000" in the add-on prefs (don't commit that here).
DEFAULT_BASE_URL = "https://apha3d-backend-6nxtf.ondigitalocean.app"

# Web app host — where the browser-loopback login page lives
# (`/plugin-auth?port=<loopback-port>`). For LOCAL dev point this at
# "http://localhost:3000" in the add-on prefs (don't commit that here).
DEFAULT_WEB_BASE_URL = "https://alpha3d.io"

# How long the loopback listener waits for the browser to hand back a
# token before giving up (seconds). Generous on purpose: the user may
# tab away mid-login, and a closed listener surfaces as a confusing
# ERR_CONNECTION_REFUSED on the web page's POST.
LOGIN_TIMEOUT_SECONDS = 600

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
    {"id": "tag_asset", "label": "Tag Asset", "icon": "BOOKMARKS"},
)

# Generation quality tiers. These mirror the web app's GenerationBox
# `meshMode` exactly (generationBox.tsx + utils/meshFaceCount.ts): same
# generateType / octreeResolution / face-count band per tier, so a job
# submitted from Blender is identical to one from the website.
#   High-Res / Ultra      -> generateType "Normal" (octree 2 vs 3)
#   Low-Poly              -> generateType "LowPoly" (octree 1, PBR forced off,
#                            hunyuanModel "3.0", explicit polygonType)
QUALITY_TABLE = {
    "HIGH_RES": {
        "label": "High-Res",
        "blurb": "200K-500K polygons - quality texture",
        "generate_type": "Normal",
        "octree": 2,
        "face_default": 200_000,
        "face_min": 200_000,
        "face_max": 500_000,
        "allows_pbr": True,
    },
    "ULTRA_HIGH_RES": {
        "label": "Ultra High-Res",
        "blurb": "500K-1.5M polygons - quality texture",
        "generate_type": "Normal",
        "octree": 3,
        "face_default": 1_000_000,
        "face_min": 500_000,
        "face_max": 1_500_000,
        "allows_pbr": True,
    },
    "LOW_POLY": {
        "label": "Low-Poly",
        "blurb": "3K-15K polygons - game-ready",
        "generate_type": "LowPoly",
        "octree": 1,
        "face_default": 9_000,
        "face_min": 3_000,
        "face_max": 15_000,
        "allows_pbr": False,
    },
}
# UI display order (matches the website dropdown).
QUALITY_ORDER = ("HIGH_RES", "ULTRA_HIGH_RES", "LOW_POLY")


def credit_cost(quality_key, enable_pbr):
    """3D-credit cost for a quality + PBR choice.

    Mirrors the backend's authoritative prices (alpha5.service.ts):
    LowPoly = 48; Normal + PBR = 42; Normal without PBR = 30. (The website
    settings modal still shows 30 for Low-Poly, but that is a known stale
    display value — the server actually bills 48, so we show 48.)
    """
    if quality_key == "LOW_POLY":
        return 48
    if enable_pbr:
        return 42
    return 30
