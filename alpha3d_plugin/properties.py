"""Runtime properties — transient per Blender session.

Lives on the WindowManager (not the Scene) so it is NOT saved into the
.blend file. The connection status line and the generation state machine
are all session-scoped and should reset when Blender restarts.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)

from .constants import QUALITY_ORDER, QUALITY_TABLE

# Static enum item list (built once at import). EnumProperty items must keep
# a stable Python reference — building them dynamically per access triggers
# Blender's string-garbage-collection bug, so we materialise them here.
_QUALITY_ITEMS = [
    (key, QUALITY_TABLE[key]["label"], QUALITY_TABLE[key]["blurb"])
    for key in QUALITY_ORDER
]

_POLY_TYPE_ITEMS = [
    ("TRIANGLE", "Triangles", "Triangulated mesh (default)"),
    ("QUAD", "Quads", "Quad-dominant mesh, better for editing and subdivision"),
]

# Shared by every mesh-in op (retopology, UV unwrap, segmentation).
_MESH_SOURCE_ITEMS = [
    ("OBJECT", "Selected object", "Use the mesh selected in the scene"),
    ("FILE", "From file", "Use a .glb file from disk"),
]

_RETOPO_DETAIL_ITEMS = [
    ("HIGH", "High", "Densest topology (octree 3)"),
    ("MEDIUM", "Medium", "Balanced topology (octree 2)"),
    ("LOW", "Low", "Lightest topology (octree 1)"),
]


def _on_quality_change(self, context):
    """Reset the polygon target to the new tier's default when the quality
    level changes (mirrors the web app, which resets faceCount per tier)."""
    tier = QUALITY_TABLE.get(self.gen_quality)
    if tier:
        self.gen_face_count = tier["face_default"]


class Alpha3DProps(bpy.types.PropertyGroup):
    """Everything the panels bind to."""

    # Short status line shown under the connection header (e.g. login result,
    # last error). Updated from the main thread only.
    status_text: StringProperty(default="")

    # ── Tools tab: Text / Image to 3D ────────────────────────────────
    gen_prompt: StringProperty(
        name="Prompt",
        description="Describe the model to generate",
        default="",
    )
    gen_image_path: StringProperty(
        name="Image",
        description="Reference image for image-to-3D. Takes priority over the prompt",
        default="",
        subtype="FILE_PATH",
    )
    gen_quality: EnumProperty(
        name="Quality",
        description="Generation quality / polygon tier (same as the web app)",
        items=_QUALITY_ITEMS,
        default="HIGH_RES",
        update=_on_quality_change,
    )
    gen_poly_type: EnumProperty(
        name="Poly Type",
        description="Low-Poly only: triangulated or quad-dominant mesh",
        items=_POLY_TYPE_ITEMS,
        default="TRIANGLE",
    )
    gen_enable_pbr: BoolProperty(
        name="PBR textures",
        description="Generate PBR texture maps. Costs more credits. Disabled for Low-Poly",
        default=True,
    )
    gen_face_count: IntProperty(
        name="Polygons",
        description="Target polygon (face) count. Clamped to the quality tier's range on submit",
        default=200_000,
        min=3_000,
        max=1_500_000,
    )
    # Generation state machine, updated from the main thread only:
    #   IDLE       — ready for input (gen_status may hold the last result/error)
    #   IMAGING    — FLUX text->image preview is running
    #   PREVIEW    — image is ready; awaiting Regenerate / Create 3D / Discard
    #   GENERATING — 3D job submitted and polling
    gen_stage: StringProperty(default="IDLE")
    gen_status: StringProperty(default="")

    # ── Smart Retopology ─────────────────────────────────────────────
    retopo_source: EnumProperty(
        name="Source",
        description="Where the mesh to retopologize comes from",
        items=_MESH_SOURCE_ITEMS,
        default="OBJECT",
    )
    retopo_file_path: StringProperty(
        name="Mesh",
        description="A .glb file to retopologize",
        default="",
        subtype="FILE_PATH",
    )
    retopo_detail: EnumProperty(
        name="Detail level",
        description="Target topology density (maps to the platform's High / Medium / Low)",
        items=_RETOPO_DETAIL_ITEMS,
        default="HIGH",
    )
    retopo_poly_type: EnumProperty(
        name="Polygon type",
        description="Output topology face type",
        items=_POLY_TYPE_ITEMS,
        default="TRIANGLE",
    )
    # Retopology state machine (main thread only): IDLE | PROCESSING.
    retopo_stage: StringProperty(default="IDLE")
    retopo_status: StringProperty(default="")

    # UV Unwrap has no properties — its panel links out to the web app's
    # /uv-unwrapping tool rather than submitting from Blender.

    # ── AI Segmentation ──────────────────────────────────────────────
    seg_source: EnumProperty(
        name="Source",
        description="Where the mesh to segment comes from",
        items=_MESH_SOURCE_ITEMS,
        default="OBJECT",
    )
    seg_file_path: StringProperty(
        name="Mesh",
        description="A .glb file to segment",
        default="",
        subtype="FILE_PATH",
    )
    seg_stage: StringProperty(default="IDLE")
    seg_status: StringProperty(default="")

    # ── AI Rigging ───────────────────────────────────────────────────
    rig_source: EnumProperty(
        name="Source",
        description="Where the humanoid mesh to rig comes from",
        items=_MESH_SOURCE_ITEMS,
        default="OBJECT",
    )
    rig_file_path: StringProperty(
        name="Mesh",
        description="A .glb file to rig",
        default="",
        subtype="FILE_PATH",
    )
    # rig_stage: IDLE | CHECKING (T-pose pre-check) | POSE_WARN | PROCESSING
    rig_stage: StringProperty(default="IDLE")
    rig_status: StringProperty(default="")
    rig_pose_warning: StringProperty(default="")


classes = (Alpha3DProps,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # The single accessor every panel/operator uses: context.window_manager.alpha3d
    bpy.types.WindowManager.alpha3d = bpy.props.PointerProperty(type=Alpha3DProps)


def unregister():
    del bpy.types.WindowManager.alpha3d
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
