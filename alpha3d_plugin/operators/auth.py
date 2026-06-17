"""Login / logout operators."""

import bpy

from ..auth import manager


class ALPHA3D_OT_login(bpy.types.Operator):
    bl_idname = "alpha3d.login"
    bl_label = "Connect Alpha3D Account"
    bl_description = (
        "Open your browser to log in and connect this plugin to your Alpha3D account"
    )

    def execute(self, context):
        manager.start_login()
        self.report(
            {"INFO"},
            "Opened your browser. Finish logging in there, then return to Blender.",
        )
        return {"FINISHED"}


class ALPHA3D_OT_logout(bpy.types.Operator):
    bl_idname = "alpha3d.logout"
    bl_label = "Disconnect"
    bl_description = "Clear the stored Alpha3D session token"

    def execute(self, context):
        manager.logout()
        self.report({"INFO"}, "Disconnected from Alpha3D.")
        return {"FINISHED"}


classes = (ALPHA3D_OT_login, ALPHA3D_OT_logout)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
