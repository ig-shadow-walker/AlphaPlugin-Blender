"""Alpha3D for Blender — the full AI 3D pipeline, inside Blender.

Architecture:
  • constants / preferences / properties — config + persisted token + transient UI state
  • mainthread                            — bpy-safe queue drained by a bpy.app.timers tick
  • api/                                   — stdlib HTTP client + endpoint wrappers (no deps)
  • auth/                                  — browser-loopback login
  • operators/                            — auth, tools, generate, library
  • panels/                               — Alpha3D sidebar: Tools · Library

Install: zip the `alpha3d_plugin/` folder and Install from Disk, or copy
it into your Blender addons directory.
"""

bl_info = {
    "name": "Alpha3D",
    "author": "Alpha3D",
    "version": (0, 6, 2),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Alpha3D",
    "description": "Alpha3D's AI 3D pipeline tools, inside Blender.",
    "category": "3D View",
}

# Submodule registration order matters: properties (PropertyGroups +
# WindowManager pointer) and preferences must exist before panels/operators
# reference them. mainthread starts the queue timer first.
from . import mainthread, preferences, properties  # noqa: E402
from . import operators as _operators  # noqa: E402
from . import panels as _panels  # noqa: E402

_MODULES = (mainthread, properties, preferences, _operators, _panels)


def register():
    for mod in _MODULES:
        mod.register()


def unregister():
    for mod in reversed(_MODULES):
        mod.unregister()


if __name__ == "__main__":
    register()
