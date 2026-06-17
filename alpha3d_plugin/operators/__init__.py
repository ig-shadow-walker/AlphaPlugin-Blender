"""Operators: auth, tools, chat."""

import bpy

from . import auth, chat, tools

_submodules = (auth, tools, chat)


def register():
    for mod in _submodules:
        mod.register()


def unregister():
    for mod in reversed(_submodules):
        mod.unregister()
