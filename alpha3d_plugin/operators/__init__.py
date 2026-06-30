"""Operators: auth, notice, meshjob, tools, generate, retopology,
segmentation, rigging, library.

(UV Unwrap has no operator here — the UV Unwrap panel links out to the web
app's /uv-unwrapping tool, because a Blender-re-exported GLB fails Tencent's
UV solver where the platform's own GLB succeeds.)"""

import bpy

from . import (
    auth,
    generate,
    library,
    meshjob,
    notice,
    retopology,
    rigging,
    segmentation,
    tools,
)

_submodules = (
    auth,
    notice,
    meshjob,
    tools,
    generate,
    retopology,
    segmentation,
    rigging,
    library,
)


def register():
    for mod in _submodules:
        mod.register()


def unregister():
    for mod in reversed(_submodules):
        mod.unregister()
