"""Sidebar panels: connection header, Tools, Library, Assistant."""

from . import assistant, library, main, tools

# main first so its CATEGORY/SPACE/REGION constants import cleanly into
# the others, and so bl_order places it at the top.
_submodules = (main, tools, library, assistant)


def register():
    for mod in _submodules:
        mod.register()


def unregister():
    for mod in reversed(_submodules):
        mod.unregister()
