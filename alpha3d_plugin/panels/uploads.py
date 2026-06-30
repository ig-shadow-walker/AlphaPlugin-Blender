"""Uploads tab — meshes the user uploaded (generationType 'upload').

Separated from the Library (generated models) the way the website splits
Uploads from Generations. Same fetch + cards + pagination as the Library;
data lives in operators/library.py.
"""

import bpy

from ..operators import library as lib
from ..preferences import is_connected
from .library import draw_view
from .main import CATEGORY, REGION, SPACE


class ALPHA3D_PT_uploads(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_uploads"
    bl_label = "Uploads"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 8
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        if not is_connected():
            layout.label(text="Connect your account to see your uploads.", icon="INFO")
            return

        # Shares the Library's fetch (it buckets assets + uploads together).
        lib.request_initial_load()

        header = layout.row(align=True)
        header.label(text="Your uploads", icon="IMPORT")
        header.operator("alpha3d.library_refresh", text="", icon="FILE_REFRESH")

        draw_view(layout, "uploads", "No uploaded models yet.")


classes = (ALPHA3D_PT_uploads,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
