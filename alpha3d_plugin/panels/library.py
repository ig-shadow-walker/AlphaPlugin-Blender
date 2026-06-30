"""Library tab — the user's generated assets.

Uploads live in their own tab; operation results aren't shown anywhere. The
card + pager helpers here are shared with the Uploads panel. Data + workers
live in operators/library.py.
"""

import bpy

from ..operators import library as lib
from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE


# ── shared draw helpers (also used by the Uploads panel) ──────────────


def draw_post_card(layout, post):
    """One post: thumbnail, title, status, and either a live download bar
    (while importing), a per-format chooser, or the import button."""
    box = layout.box()

    icon_id = lib.get_thumb_icon_id(post["id"])
    if icon_id:
        box.template_icon(icon_value=icon_id, scale=5.0)

    box.label(text=post["title"] or "Untitled")

    label, icon = lib.status_display(post["status"])
    box.label(text=label, icon=icon)

    if post["status"] != "completed":
        return

    progress = lib.get_import_progress(post["id"])
    if progress is not None:
        if progress < 0:
            box.label(text="Downloading...", icon="IMPORT")
        elif hasattr(box, "progress"):
            box.progress(
                factor=progress / 100.0,
                text=f"Downloading {progress}%",
                type="BAR",
            )
        else:  # Blender < 4.0 has no UILayout.progress
            box.label(text=f"Downloading {progress}%", icon="IMPORT")
        return

    formats = lib.get_formats(post["id"])
    if formats and len(formats) > 1:
        box.label(text="Import as:")
        row = box.row(align=True)
        for fmt in formats:
            op = row.operator(
                "alpha3d.library_import", text=fmt.upper(), icon="IMPORT"
            )
            op.post_id = post["id"]
            op.fmt = fmt
    else:
        op = box.operator(
            "alpha3d.library_import", text="Import to scene", icon="IMPORT"
        )
        op.post_id = post["id"]
        op.fmt = ""


def draw_pager(layout, view, info):
    """Prev / page-indicator / Next for the given view."""
    current, total, _count = info
    if total <= 1:
        return
    row = layout.row(align=True)
    prev = row.row(align=True)
    prev.enabled = current > 1
    op = prev.operator("alpha3d.library_page", text="", icon="TRIA_LEFT")
    op.view = view
    op.delta = -1
    row.label(text=f"Page {current} / {total}")
    nxt = row.row(align=True)
    nxt.enabled = current < total
    op = nxt.operator("alpha3d.library_page", text="", icon="TRIA_RIGHT")
    op.view = view
    op.delta = 1


def draw_view(layout, view, empty_text):
    """Shared body for a paged view (Library / Uploads)."""
    action = lib.get_action()
    if action and lib.action_belongs_to_view(view):
        layout.label(text=action, icon="INFO")
    error = lib.get_error()
    if error:
        layout.label(text=error, icon="ERROR")
    if lib.is_loading():
        layout.label(text="Loading...", icon="SORTTIME")

    page = lib.get_page(view)
    if not page and not lib.is_loading() and not error:
        layout.label(text=empty_text, icon="INFO")
        return

    for post in page:
        draw_post_card(layout, post)
    draw_pager(layout, view, lib.page_info(view))


class ALPHA3D_PT_library(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_library"
    bl_label = "Library"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 7
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        if not is_connected():
            layout.label(text="Connect your account to see your models.", icon="INFO")
            return

        lib.request_initial_load()

        header = layout.row(align=True)
        header.label(text="Your generations", icon="ASSET_MANAGER")
        header.operator("alpha3d.library_refresh", text="", icon="FILE_REFRESH")

        draw_view(layout, "assets", "No models yet. Generate one in Tools.")


classes = (ALPHA3D_PT_library,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
