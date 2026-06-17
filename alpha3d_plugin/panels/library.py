"""Library tab — browse and pull in the user's Alpha3D generations.

Phase 0: a placeholder. Later phases fill this with a thumbnail grid
(paged + searchable) wired to the user's posts; clicking a tile imports
the mesh into the scene or hands it to a tool.
"""

import bpy

from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE


class ALPHA3D_PT_library(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_library"
    bl_label = "Library"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.enabled = is_connected()
        layout.label(text="Your generations", icon="ASSET_MANAGER")
        layout.label(text="Browsing arrives in a later phase.")


classes = (ALPHA3D_PT_library,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
