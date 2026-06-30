"""Scene-import helpers (bpy — MAIN THREAD only)."""

import bpy

from . import mainthread


def _active_collection():
    """The collection new objects go into — so the parent Empty and the parts
    live together and the outliner nests them. Falls back to the scene root."""
    vl = bpy.context.view_layer
    alc = getattr(vl, "active_layer_collection", None) if vl else None
    if alc is not None and alc.collection is not None:
        return alc.collection
    return bpy.context.scene.collection


def import_parts_under_parent(paths, parent_name):
    """Import each part GLB and group the parts' MESHES directly under one new
    Empty, so a segmentation reads as a single model whose children are the
    part meshes (not buried inside per-part "world" wrapper nodes).

    For each GLB the glTF importer typically makes a transform-node Empty
    (e.g. "world") with the mesh parented under it. We re-parent the MESH
    objects straight to our Empty (keeping their world pose), drop them into
    the Empty's collection so the outliner nests them, then delete the now-
    empty wrapper nodes. MAIN THREAD ONLY.

    Returns the number of meshes parented (0 means nothing imported, and the
    empty parent is removed).
    """
    coll = _active_collection()
    parent = bpy.data.objects.new(parent_name or "Segmented model", None)
    parent.empty_display_size = 0.0  # invisible group node (select via Outliner)
    coll.objects.link(parent)

    parts = 0
    wrappers = []  # gltf transform-node Empties to delete once emptied
    for path in paths:
        before = set(bpy.context.scene.objects)
        try:
            mainthread.run_in_view3d_context(
                lambda p=path: bpy.ops.import_scene.gltf(filepath=p)
            )
        except Exception as exc:  # noqa: BLE001 — skip a bad part; clean up + log
            print(f"[Alpha3D] segment part import failed ({path}): {exc!r}")
            for o in [x for x in bpy.context.scene.objects if x not in before]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except Exception:  # noqa: BLE001
                    pass
            continue
        # The glTF importer leaves exactly the freshly-imported objects selected.
        new_objs = [o for o in bpy.context.selected_objects if o not in before]
        for o in new_objs:
            if o.type == "EMPTY":
                wrappers.append(o)  # the "world"/scene wrapper — remove later
                continue
            # Re-parent the real content (mesh, and any armature/etc.) straight
            # to our Empty, keeping its world pose, and move it into the Empty's
            # collection so the outliner nests it.
            world = o.matrix_world.copy()
            o.parent = parent
            o.matrix_parent_inverse = parent.matrix_world.inverted()
            o.matrix_world = world
            for c in list(o.users_collection):
                if c is not coll:
                    c.objects.unlink(o)
            if coll not in o.users_collection:
                coll.objects.link(o)
            parts += 1

    for w in wrappers:
        try:
            bpy.data.objects.remove(w, do_unlink=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Alpha3D] could not remove wrapper {w.name!r}: {exc!r}")

    if parts == 0:
        bpy.data.objects.remove(parent, do_unlink=True)
        return 0
    return parts
