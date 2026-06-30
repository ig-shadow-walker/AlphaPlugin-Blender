"""A dismissible one-line notice for the Alpha3D sidebar.

State lives here (module-level, set from the MAIN THREAD when something
finishes — e.g. a generation completes and imports). The connection-header
panel renders it as a banner with a close button until the user dismisses
it, and `show()` also fires a best-effort transient popup so the notice is
visible even when the Alpha3D tab is not the focused N-panel.
"""

import bpy

from .. import mainthread

_message = ""
_icon = "CHECKMARK"


def show(message, icon="CHECKMARK", popup=True):
    """Raise a notice. MAIN THREAD ONLY.

    Sets the persistent banner and (optionally) fires a one-off popup over
    the active area. Overwrites any previous notice.
    """
    global _message, _icon
    _message = message
    _icon = icon
    mainthread.tag_redraw_all()
    if popup:
        _try_popup(message, icon)


def clear():
    """Dismiss the current notice. MAIN THREAD ONLY."""
    global _message
    _message = ""
    mainthread.tag_redraw_all()


def current():
    """(message, icon). `message` is '' when there is nothing to show."""
    return (_message, _icon)


def _try_popup(message, icon):
    """Best-effort transient popup over the current area. Never raises —
    popups need a window context that may be absent from a timer tick."""
    wm = bpy.context.window_manager
    if not wm:
        return

    def draw(self, _context):
        self.layout.label(text=message)

    try:
        wm.popup_menu(draw, title="Alpha3D", icon=icon)
    except Exception:  # noqa: BLE001
        pass


class ALPHA3D_OT_dismiss_notice(bpy.types.Operator):
    bl_idname = "alpha3d.dismiss_notice"
    bl_label = "Dismiss"
    bl_description = "Dismiss this notice"

    def execute(self, context):
        clear()
        return {"FINISHED"}


classes = (ALPHA3D_OT_dismiss_notice,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _message
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _message = ""
