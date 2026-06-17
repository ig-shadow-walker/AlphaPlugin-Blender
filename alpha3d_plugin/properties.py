"""Runtime properties — transient per Blender session.

Lives on the WindowManager (not the Scene) so it is NOT saved into the
.blend file. The chat log, current session id, and streaming flag are
all session-scoped and should reset when Blender restarts.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)


class Alpha3DChatMessage(bpy.types.PropertyGroup):
    """One line in the Assistant transcript."""

    # 'user' | 'assistant' | 'system' | 'tool'
    role: StringProperty(default="assistant")
    text: StringProperty(default="")


class Alpha3DProps(bpy.types.PropertyGroup):
    """Everything the panels bind to."""

    chat_input: StringProperty(
        name="Message",
        description="Ask Alphred to do something in Blender or on Alpha3D",
        default="",
    )
    messages: CollectionProperty(type=Alpha3DChatMessage)
    session_id: IntProperty(default=0)
    is_streaming: BoolProperty(default=False)
    # Short status line shown under the connection header (e.g. login result,
    # last error). Updated from the main thread only.
    status_text: StringProperty(default="")


classes = (Alpha3DChatMessage, Alpha3DProps)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # The single accessor every panel/operator uses: context.window_manager.alpha3d
    bpy.types.WindowManager.alpha3d = bpy.props.PointerProperty(type=Alpha3DProps)


def unregister():
    del bpy.types.WindowManager.alpha3d
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
