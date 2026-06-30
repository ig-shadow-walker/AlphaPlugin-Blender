"""Sidebar panels: connection header, Tools, Smart Retopology, UV Unwrap,
AI Texturing, AI Segmentation, AI Rigging, Library, Uploads, Asset Tagging.

UV Unwrap, AI Texturing and Asset Tagging are link-out panels (they open the
web app): Tencent's UV/texturing pipelines run against your generation's
original mesh and tagging operates on your saved library, so they aren't run
from a Blender re-export."""

from . import (
    library,
    main,
    retopology,
    rigging,
    segmentation,
    tagging,
    texturing,
    tools,
    uploads,
    uvunwrap,
)

# main first so its CATEGORY/SPACE/REGION constants import cleanly into the
# others, and so bl_order places it at the top. library before uploads so
# uploads can import the shared draw helpers from it.
_submodules = (
    main, tools, retopology, uvunwrap, texturing, segmentation, rigging,
    library, uploads, tagging,
)


def register():
    for mod in _submodules:
        mod.register()


def unregister():
    for mod in reversed(_submodules):
        mod.unregister()
