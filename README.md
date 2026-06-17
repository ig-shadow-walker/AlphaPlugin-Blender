# Alpha3D for Blender

Alpha3D's AI 3D pipeline and the Alphred assistant, inside Blender. Run
each Alpha3D tool on your active object, browse your generations, and
talk to Alphred without leaving the viewport.

This repo is the **client-side Blender add-on**. It talks to the same
Alpha3D backend and reuses the Alphred orchestration engine; the server
scopes sessions by `surface: 'blender'` so the assistant behaves
differently here than on the web.

## Status — Phase 0 (running scaffold)

A loadable add-on with the full plumbing in place. What works today:

- **Login** via browser loopback (your normal Alpha3D account; a 30-day
  token is stored in add-on preferences).
- **Assistant tab** — live Alphred chat over SSE (text replies stream in).
- **Tools / Library tabs** — laid out and wired to operators; the actual
  job calls are stubs until the next phase.

Not yet built (by design): running real pipeline jobs from the Tools
tab, the Library thumbnail grid, and **client-executed (bpy) tools** —
those need the backend turn-loop pause/resume work, which only pays off
once bpy tools exist.

## Install (development)

1. Zip the `alpha3d_plugin/` folder (the folder itself, so the zip
   contains `alpha3d_plugin/__init__.py`).
2. Blender → Edit → Preferences → Add-ons → Install from Disk → pick the zip.
3. Enable **Alpha3D**.
4. Open the N-panel in the 3D viewport → **Alpha3D** tab → **Connect**.

During development you can instead symlink/copy `alpha3d_plugin/` into
your Blender `scripts/addons/` directory and toggle the add-on to reload.

### Pointing at a different backend

Edit → Preferences → Add-ons → Alpha3D → expand it:

- **API URL** — backend host (default `https://api.alpha3d.io`).
- **Web URL** — web app host used for browser login (default
  `https://alpha3d.io`). The login page lives at `/plugin-auth`.

## Architecture

```
alpha3d_plugin/
  __init__.py        bl_info + ordered register/unregister
  constants.py       addon id, default hosts, curated tool list
  preferences.py     AddonPreferences (persisted token + hosts) + get_prefs()
  properties.py      transient per-session UI state on WindowManager
  mainthread.py      bpy-safe task queue drained by a bpy.app.timers tick
  api/
    client.py        stdlib HTTP + SSE client (no external deps)
    endpoints.py     create_session / send_message_stream / submit_tool_result / ...
  auth/
    loopback.py      127.0.0.1 listener that catches the JWT from the browser
    manager.py       opens the browser, persists the token on the main thread
  operators/
    auth.py          login / logout
    tools.py         generic run_tool (Phase 0 stub)
    chat.py          send_message / clear_chat (live SSE streaming)
  panels/
    main.py          connection header
    tools.py         Tools tab
    library.py       Library tab (placeholder)
    assistant.py     Assistant tab (chat)
```

### Threading rule

`bpy` is main-thread only. All network work (login loopback, SSE
streaming) runs on daemon threads; results are marshalled back to the
main thread via `mainthread.run_on_main_thread(...)` before touching any
`bpy` data or UI prop.

### Auth

Login never handles your password. The add-on opens
`<web>/plugin-auth?port=<loopback-port>` in your browser; the Alpha3D web
app POSTs your existing session token back to the local loopback port.
The token is your standard 30-day account JWT, stored in add-on prefs.
