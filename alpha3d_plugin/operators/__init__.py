"""Operators: auth, tools, generate, chat."""

import bpy

from . import auth, chat, generate, tools

_submodules = (auth, tools, generate, chat)


def register():
    for mod in _submodules:
        mod.register()


def unregister():
    for mod in reversed(_submodules):
        mod.unregister()
