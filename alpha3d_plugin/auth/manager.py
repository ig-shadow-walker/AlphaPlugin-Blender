"""Login / logout orchestration.

Ties the loopback listener to Blender: opens the browser, waits for the
token on a background thread, then marshals the result onto the main
thread to write preferences and refresh the UI.
"""

import webbrowser

import bpy

from .. import mainthread
from ..constants import DEFAULT_WEB_BASE_URL
from ..preferences import get_prefs
from .loopback import start_loopback


def _set_status(text):
    """Update the transient status line (main thread only)."""
    wm = bpy.context.window_manager
    if wm and hasattr(wm, "alpha3d"):
        wm.alpha3d.status_text = text
    mainthread.tag_redraw_all()


def _persist_token(token):
    """Runs on the main thread: store the token and save user prefs."""
    prefs = get_prefs()
    prefs.token = token
    # Force-write userprefs so the 30-day session survives a restart even
    # if "Auto-Save Preferences" is off.
    try:
        bpy.ops.wm.save_userpref()
    except Exception as exc:
        print(f"[Alpha3D] could not auto-save preferences: {exc!r}")
    _set_status("Connected to your Alpha3D account.")


def start_login():
    """Kick off the browser-loopback login. Returns immediately."""
    prefs = get_prefs()
    web_base = (prefs.web_base_url or DEFAULT_WEB_BASE_URL).rstrip("/")

    def on_token(token):
        mainthread.run_on_main_thread(lambda: _persist_token(token))

    def on_timeout():
        mainthread.run_on_main_thread(
            lambda: _set_status("Login timed out. Try connecting again.")
        )

    port = start_loopback(on_token, on_timeout=on_timeout)
    url = f"{web_base}/plugin-auth?port={port}"
    webbrowser.open(url)
    _set_status("Waiting for browser login…")


def logout():
    """Clear the stored token."""
    prefs = get_prefs()
    prefs.token = ""
    try:
        bpy.ops.wm.save_userpref()
    except Exception:
        pass
    _set_status("Disconnected.")
