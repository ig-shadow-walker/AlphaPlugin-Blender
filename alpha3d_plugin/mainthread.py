"""Main-thread task queue.

`bpy` is not thread-safe: touching `bpy.data`, operators, or UI props
from a background thread crashes Blender. But our network work (login
loopback, SSE streaming) MUST run off the main thread or it freezes the
viewport.

The bridge is this queue. Background threads push a zero-arg callable
with `run_on_main_thread(fn)`; a `bpy.app.timers` callback drains the
queue and runs each callable on the main thread on the next tick.
"""

import queue

import bpy

# stdlib `queue.Queue` is thread-safe (internally locked), so producers
# on worker threads and the single main-thread consumer are safe.
_tasks: "queue.Queue" = queue.Queue()


def run_on_main_thread(fn):
    """Schedule `fn` (a zero-arg callable) to run on Blender's main thread.

    Safe to call from any thread. Returns immediately; `fn` runs on the
    next timer tick (<= ~0.2s later).
    """
    _tasks.put(fn)


def _drain():
    """Timer callback: run every queued task on the main thread."""
    while True:
        try:
            fn = _tasks.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception as exc:  # never let one bad task kill the timer
            print(f"[Alpha3D] main-thread task error: {exc!r}")
    # Re-arm: returning a float reschedules the timer that many seconds out.
    return 0.2


def run_in_view3d_context(fn):
    """Run `fn` (which invokes a bpy operator) under a window / VIEW_3D context
    override. MAIN THREAD ONLY.

    Operators like `import_scene.gltf` invoked from this module's timer-drain
    callback have no active window/area in `bpy.context` and can fail a
    poll/context check ("context is incorrect"). Wrapping the call in a
    temp_override with a real window (and a 3D viewport when one exists) gives
    them the context they expect. Falls back to a direct call when no window
    or `temp_override` is available (older Blender / headless).
    """
    wm = bpy.context.window_manager
    win = wm.windows[0] if (wm and wm.windows) else None
    temp_override = getattr(bpy.context, "temp_override", None)
    if win is None or temp_override is None:
        fn()
        return
    ctx = {"window": win}
    screen = getattr(win, "screen", None)
    if screen:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                ctx["area"] = area
                region = next(
                    (r for r in area.regions if r.type == "WINDOW"), None
                )
                if region:
                    ctx["region"] = region
                break
    try:
        with temp_override(**ctx):
            fn()
    except TypeError:
        fn()  # temp_override signature mismatch — best effort


def tag_redraw_all():
    """Force every visible region to redraw.

    Call (on the main thread) after mutating UI props from a streamed
    response so the panel reflects the change immediately instead of on
    the next user interaction.
    """
    wm = bpy.context.window_manager
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def register():
    if not bpy.app.timers.is_registered(_drain):
        # persistent=True keeps the timer alive across .blend file loads.
        bpy.app.timers.register(_drain, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    # Drop any tasks still queued so they don't run against a half-torn-down
    # add-on on the next register.
    try:
        while True:
            _tasks.get_nowait()
    except queue.Empty:
        pass
