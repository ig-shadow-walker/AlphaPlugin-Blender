"""Assistant tab — the Alphred chat (and, later, in-Blender actions)."""

import bpy

from ..preferences import is_connected
from .main import CATEGORY, REGION, SPACE

_ROLE_ICON = {
    "user": "USER",
    "assistant": "OUTLINER_OB_LIGHT",
    "system": "INFO",
    "tool": "TOOL_SETTINGS",
}

# Rough character width before wrapping a transcript line into the next
# row. Blender labels don't auto-wrap, so we hard-wrap ourselves.
_WRAP = 38


def _draw_wrapped(layout, text, icon):
    """Draw `text` across as many label rows as it needs."""
    first = True
    for paragraph in text.split("\n"):
        if paragraph == "":
            layout.label(text="")
            continue
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > _WRAP and line:
                layout.label(text=line, icon=icon if first else "BLANK1")
                first = False
                line = word
            else:
                line = candidate
        if line:
            layout.label(text=line, icon=icon if first else "BLANK1")
            first = False


class ALPHA3D_PT_assistant(bpy.types.Panel):
    bl_idname = "ALPHA3D_PT_assistant"
    bl_label = "Assistant"
    bl_space_type = SPACE
    bl_region_type = REGION
    bl_category = CATEGORY
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        props = context.window_manager.alpha3d
        layout.enabled = is_connected()

        # Transcript
        box = layout.box()
        if not props.messages:
            box.label(text="Ask Alphred anything about your 3D work.", icon="OUTLINER_OB_LIGHT")
        else:
            col = box.column(align=True)
            for msg in props.messages:
                icon = _ROLE_ICON.get(msg.role, "DOT")
                _draw_wrapped(col, msg.text or "…", icon)
                col.separator(factor=0.3)

        if props.is_streaming:
            layout.label(text="Alphred is thinking…", icon="SORTTIME")

        # Composer
        layout.prop(props, "chat_input", text="")
        row = layout.row(align=True)
        send = row.row(align=True)
        send.enabled = not props.is_streaming
        send.operator("alpha3d.send_message", text="Send", icon="EXPORT")
        row.operator("alpha3d.clear_chat", text="", icon="TRASH")


classes = (ALPHA3D_PT_assistant,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
