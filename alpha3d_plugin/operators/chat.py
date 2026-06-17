"""Assistant chat operators — the Alphred conversation, end to end.

Send flow:
  1. Append the user's message to the transcript (main thread).
  2. On a background thread: ensure a Blender-surface session exists,
     then open the SSE stream.
  3. Each SSE frame is marshalled back to the main thread to mutate the
     transcript props and tag a redraw.

`bpy` is touched ONLY on the main thread; the network runs on a worker.
"""

import json
import threading

import bpy

from .. import mainthread
from ..api import endpoints
from ..api.client import ApiError
from ..preferences import is_connected

# Index of the assistant message currently being streamed into, or None.
# Only one turn streams at a time (guarded by props.is_streaming).
_active_idx = None


# ── main-thread mutations ────────────────────────────────────────────


def _props():
    wm = bpy.context.window_manager
    return wm.alpha3d if wm and hasattr(wm, "alpha3d") else None


def _add_message(role, text):
    props = _props()
    if not props:
        return None
    msg = props.messages.add()
    msg.role = role
    msg.text = text
    mainthread.tag_redraw_all()
    return len(props.messages) - 1


def _begin_assistant():
    global _active_idx
    _active_idx = _add_message("assistant", "")


def _append_assistant_text(chunk):
    props = _props()
    if not props or _active_idx is None or _active_idx >= len(props.messages):
        return
    props.messages[_active_idx].text += chunk
    mainthread.tag_redraw_all()


def _add_system(text):
    _add_message("system", text)


def _finish_stream(error_text=None):
    global _active_idx
    props = _props()
    if props:
        props.is_streaming = False
        if error_text:
            _add_message("system", error_text)
    _active_idx = None
    mainthread.tag_redraw_all()


# ── SSE frame handling (called on the worker thread) ─────────────────


def _on_event(name, data):
    """Dispatch one SSE frame. Runs on the worker thread, so every UI
    mutation is wrapped in run_on_main_thread."""
    payload = None
    try:
        payload = json.loads(data) if data else None
    except Exception:
        payload = None

    if name == "text_delta":
        text = ""
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("delta") or ""
        elif isinstance(payload, str):
            text = payload
        if text:
            mainthread.run_on_main_thread(lambda t=text: _append_assistant_text(t))

    elif name == "tool_use_start":
        tool_name = payload.get("name") if isinstance(payload, dict) else None
        if tool_name:
            mainthread.run_on_main_thread(
                lambda n=tool_name: _add_system(f"Running {n}…")
            )

    elif name == "error":
        msg = "Something went wrong."
        if isinstance(payload, dict):
            msg = payload.get("message") or payload.get("error") or msg
        mainthread.run_on_main_thread(lambda m=msg: _finish_stream(f"Error: {m}"))

    elif name == "turn_end":
        mainthread.run_on_main_thread(lambda: _finish_stream())

    # route / tool_use_end / tool_result / user_message_saved: ignored in
    # the Phase 0 transcript (no client tools to act on yet).


def _run_turn(session_id_holder, text):
    """Worker-thread body: ensure session, then stream the turn."""
    try:
        session_id = session_id_holder["id"]
        if not session_id:
            created = endpoints.create_session(surface="blender")
            session_id = (created or {}).get("data", {}).get("id")
            if not session_id:
                raise ApiError(0, "Could not start a session.")
            sid = session_id
            mainthread.run_on_main_thread(lambda: _set_session_id(sid))

        mainthread.run_on_main_thread(_begin_assistant)
        endpoints.send_message_stream(
            session_id,
            text,
            _on_event,
            should_stop=lambda: not _streaming(),
        )
        # If the stream ends without a turn_end (e.g. dropped connection),
        # make sure we clear the streaming flag.
        mainthread.run_on_main_thread(lambda: _finish_stream())
    except ApiError as exc:
        mainthread.run_on_main_thread(lambda e=exc: _finish_stream(f"Error: {e.message}"))
    except Exception as exc:  # noqa: BLE001
        mainthread.run_on_main_thread(
            lambda e=exc: _finish_stream(f"Error: {e!r}")
        )


def _streaming():
    props = _props()
    return bool(props and props.is_streaming)


def _set_session_id(session_id):
    props = _props()
    if props:
        props.session_id = session_id


# ── operators ────────────────────────────────────────────────────────


class ALPHA3D_OT_send_message(bpy.types.Operator):
    bl_idname = "alpha3d.send_message"
    bl_label = "Send"
    bl_description = "Send your message to the Alphred assistant"

    def execute(self, context):
        props = context.window_manager.alpha3d
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if props.is_streaming:
            self.report({"WARNING"}, "Alphred is still replying.")
            return {"CANCELLED"}

        text = (props.chat_input or "").strip()
        if not text:
            return {"CANCELLED"}

        _add_message("user", text)
        props.chat_input = ""
        props.is_streaming = True

        holder = {"id": props.session_id}
        threading.Thread(
            target=_run_turn, args=(holder, text), daemon=True, name="Alpha3D-chat"
        ).start()
        return {"FINISHED"}


class ALPHA3D_OT_clear_chat(bpy.types.Operator):
    bl_idname = "alpha3d.clear_chat"
    bl_label = "New Chat"
    bl_description = "Clear the transcript and start a fresh session"

    def execute(self, context):
        props = context.window_manager.alpha3d
        if props.is_streaming:
            self.report({"WARNING"}, "Wait for the current reply to finish.")
            return {"CANCELLED"}
        props.messages.clear()
        props.session_id = 0
        props.status_text = ""
        return {"FINISHED"}


classes = (ALPHA3D_OT_send_message, ALPHA3D_OT_clear_chat)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
