"""Library + Uploads — browse and import the user's posts.

Posts are sorted into named VIEWS, each its own sidebar tab, each paged
client-side (the website paginates too):
  • "assets"  — generated models (text/image -> 3D): the Library tab.
  • "uploads" — meshes the user uploaded (generationType 'upload').
Operation results (UV unwrap / retopology / segmentation) are skipped — they
are records of actions, not models to import, so they appear in no tab (they
still live on the platform).

We accumulate the user's posts across the server's pages (bounded), bucket
them into views, and page each view's list. Import shows a live download
percentage on the button itself.

Threading: the list fetch, thumbnail downloads, and GLB download all run on a
daemon thread; bpy and the preview-image collection are touched ONLY on the
main thread via mainthread.run_on_main_thread.
"""

import math
import os
import tempfile
import threading

import bpy
import bpy.utils.previews

from . import notice
from .. import glbutil, mainthread, sceneimport
from ..api import endpoints
from ..api.client import ApiError
from ..preferences import is_connected

_FETCH_LIMIT = 50  # posts per server request while accumulating
_MAX_FETCH_POSTS = 300  # safety cap on total posts SEEN (all buckets + skipped)
_PAGE_SIZE = 8  # posts shown per client-side page (per view)
_AUTO_REFRESH_SECONDS = 10.0

# Named views, in sidebar-tab order. Each gets its own list + page index.
_VIEW_KEYS = ("assets", "uploads")

# Generation types HIDDEN from the Library. Only UV unwrap stays hidden — it
# was moved out of the plugin to a web link, so its only posts are old test
# records (clutter). Generation, retopology, AND segmentation jobs all show in
# the Library so every job the plugin submits is trackable there. Compared
# against the generationType with any "alpha-5-" prefix stripped.
_OPERATION_RESULT_TYPES = {"uv_unwrap"}
# Belt-and-suspenders: UV unwrap posts are auto-titled "UV Unwrap - ..." —
# match the title too so a legacy variant (e.g. partuv) is still hidden.
_OPERATION_RESULT_TITLE_PREFIXES = ("uv unwrap",)


def _strip_alpha5(generation_type):
    t = generation_type or ""
    return t[len("alpha-5-"):] if t.startswith("alpha-5-") else t


def _is_operation_result(generation_type, title=""):
    if _strip_alpha5(generation_type) in _OPERATION_RESULT_TYPES:
        return True
    lt = (title or "").strip().lower()
    return any(lt.startswith(p) for p in _OPERATION_RESULT_TITLE_PREFIXES)


def _is_upload(generation_type):
    return _strip_alpha5(generation_type) == "upload"


def _view_for(generation_type, title):
    """Which tab a post belongs to, or None to skip it entirely."""
    if _is_operation_result(generation_type, title):
        return None
    if _is_upload(generation_type):
        return "uploads"
    return "assets"


# Terminal statuses (everything else is an in-progress stage).
_TERMINAL = {"completed", "error"}
# status -> (label, blender icon). Mirrors the platform's getStatusDisplay.
_STATUS_DISPLAY = {
    "new": ("Pending", "SORTTIME"),
    "starting": ("Queued", "SORTTIME"),
    "sculpting": ("Sculpting", "SORTTIME"),
    "meshing": ("Meshing", "SORTTIME"),
    "texturing": ("Texturing", "SORTTIME"),
    "extracting_mesh": ("Extracting mesh", "SORTTIME"),
    "extracting_textured": ("Saving", "SORTTIME"),
    "completed": ("Completed", "CHECKMARK"),
    "error": ("Failed", "ERROR"),
}


def status_display(status):
    return _STATUS_DISPLAY.get(status, ("Working", "SORTTIME"))


# ── module state (read by the panels, mutated on the main thread) ─────
_views = {k: [] for k in _VIEW_KEYS}  # view name -> list of post dicts
_pages = {k: 0 for k in _VIEW_KEYS}  # view name -> 0-indexed current page
_loading = False
_error = ""
_action = ""  # transient import/action status line
_action_post_id = None  # post the action refers to (None = show in every tab)
_ever_fetched = False
_auto_pending = False  # a one-shot auto-refresh timer is registered
_fetch_active = False  # a list-fetch worker is in flight (single-flight guard)
_refetch_requested = False  # a refresh was asked for while a fetch was running
_alive = True  # set False in unregister() so late-draining tasks no-op

_thumb_coll = None  # bpy.utils.previews collection, keyed by str(post id)
_thumb_files = {}  # post id -> downloaded temp file path (download-once cache)
_thumb_pending = set()  # post ids whose thumbnail download is in flight
_formats = {}  # post id -> ordered importable mesh format keys (resolved on import)
_import_progress = {}  # post id -> download percent (0-100), or -1 indeterminate
_progress_throttle = {}  # post id -> last reported percent (worker-side only)
_importing = set()  # post ids with an import in flight (dedup concurrent clicks)

_MESH_FORMATS = ("glb", "obj", "fbx", "stl")


# ── paging helpers ────────────────────────────────────────────────────


def _total_pages(count):
    return max(1, math.ceil(count / _PAGE_SIZE))


def _clamp_page(page, count):
    return max(0, min(page, _total_pages(count) - 1))


def _page_slice(lst, page):
    start = page * _PAGE_SIZE
    return lst[start:start + _PAGE_SIZE]


def _first_visible_id(lst, page):
    sl = _page_slice(lst, page)
    return sl[0]["id"] if sl else None


def _page_for_id(lst, anchor_id, fallback_page):
    """Page that now holds anchor_id, so a refresh inserting newer posts at the
    front doesn't shift the cards the user is reading. Falls back to the
    clamped previous page when the anchor is gone."""
    if anchor_id is not None:
        for i, p in enumerate(lst):
            if p["id"] == anchor_id:
                return i // _PAGE_SIZE
    return _clamp_page(fallback_page, len(lst))


# ── panel accessors (main thread) ────────────────────────────────────


def get_page(view):
    return _page_slice(_views.get(view, []), _pages.get(view, 0))


def page_info(view):
    """(current_page_1indexed, total_pages, total_count) for a view."""
    lst = _views.get(view, [])
    return (_pages.get(view, 0) + 1, _total_pages(len(lst)), len(lst))


def is_loading():
    return _loading


def get_error():
    return _error


def get_action():
    return _action


def action_belongs_to_view(view):
    """Whether the current action line should show in this view's tab. A
    post-specific action (Importing/Imported/failed for post N) shows only in
    the tab holding that post; a generic action (post_id None) shows in all."""
    if _action_post_id is None:
        return True
    return any(p["id"] == _action_post_id for p in _views.get(view, []))


def get_thumb_icon_id(post_id):
    key = str(post_id)
    if _thumb_coll is not None and key in _thumb_coll:
        return _thumb_coll[key].icon_id
    return 0


def get_formats(post_id):
    return _formats.get(post_id)


def get_import_progress(post_id):
    """Download percent (0-100) while importing, -1 when size unknown, or None
    when not importing. Drives the progress shown on the button."""
    return _import_progress.get(post_id)


# ── objFiles format helpers ──────────────────────────────────────────


def _mesh_formats_from_objfiles(obj_files):
    if not isinstance(obj_files, dict):
        return []
    if "obj_url" in obj_files:  # legacy obj+mtl pair
        return ["obj"] if obj_files.get("obj_url") else []
    return [fmt for fmt in _MESH_FORMATS if obj_files.get(fmt)]


def _url_for_format(obj_files, fmt):
    if not isinstance(obj_files, dict):
        return None
    if fmt == "obj" and "obj_url" in obj_files:
        return obj_files.get("obj_url")
    return obj_files.get(fmt)


def _segment_part_urls(obj_files):
    """Sorted part_N download URLs for a segmentation post. Segmentation ships
    N separate part meshes (objFiles.part_0..part_N) plus a part_0 mirror at
    objFiles.glb — importing the post should bring in ALL parts, not just one."""
    if not isinstance(obj_files, dict):
        return []
    parts = []
    for key, url in obj_files.items():
        if key.startswith("part_") and url:
            try:
                idx = int(key.split("_", 1)[1])
            except ValueError:
                idx = 0
            parts.append((idx, url))
    parts.sort(key=lambda p: p[0])
    return [u for _, u in parts]


# ── preview collection (main thread only) ────────────────────────────


def _ensure_thumb_coll():
    global _thumb_coll
    if _thumb_coll is None:
        _thumb_coll = bpy.utils.previews.new()
    return _thumb_coll


def _has_in_progress():
    return any(
        p["status"] not in _TERMINAL for key in _VIEW_KEYS for p in _views[key]
    )


# ── status setters (main thread) ─────────────────────────────────────


def _set_error(message):
    global _loading, _error, _fetch_active
    _fetch_active = False
    _loading = False
    _error = message
    mainthread.tag_redraw_all()


def _set_action(message, post_id=None):
    global _action, _action_post_id
    _action = message
    _action_post_id = post_id
    mainthread.tag_redraw_all()


def _set_action_async(message, post_id=None):
    mainthread.run_on_main_thread(lambda m=message, p=post_id: _set_action(m, p))


def _set_formats(post_id, formats):
    if not _alive:
        return
    _formats[post_id] = formats
    mainthread.tag_redraw_all()


def _set_import_progress(post_id, pct):
    if not _alive:
        return
    _import_progress[post_id] = pct
    mainthread.tag_redraw_all()


def _clear_import_progress(post_id):
    _import_progress.pop(post_id, None)
    _importing.discard(post_id)  # release the dedup guard
    mainthread.tag_redraw_all()


# ── list fetch (accumulate + bucket into views) ───────────────────────


def _start_fetch(quiet=False):
    """Begin a list refresh. Main thread only. Single-flight."""
    global _loading, _error, _ever_fetched, _fetch_active
    if not _alive or _fetch_active:
        return
    _fetch_active = True
    _ever_fetched = True
    _error = ""
    if not quiet:
        _loading = True
    mainthread.tag_redraw_all()
    threading.Thread(target=_run_fetch, daemon=True, name="Alpha3D-library").start()


def request_initial_load():
    """Trigger the first list fetch if it has not happened yet. Safe from a
    panel draw: only flips a flag + enqueues a main-thread task."""
    global _ever_fetched
    if _ever_fetched or _loading:
        return
    _ever_fetched = True
    mainthread.run_on_main_thread(lambda: _start_fetch())


def request_refresh():
    """Public: refresh the Library list so a job just submitted from another
    flow (generate / retopology / segmentation) shows up with its current
    status. MAIN THREAD ONLY. If a fetch is already running it may predate the
    new post, so queue one more pass to run when it finishes."""
    global _refetch_requested, _ever_fetched
    if not _alive or not is_connected():
        return  # gate like _auto_refresh_tick — no stray error banner
    _ever_fetched = True
    if _fetch_active:
        _refetch_requested = True
    else:
        _start_fetch(quiet=True)


def _run_fetch():
    """Worker: page through the user's posts (metadata only), bucket each into
    a view (skipping operation results), hand back to main."""
    try:
        buckets = {k: [] for k in _VIEW_KEYS}
        seen = 0
        page = 1
        total_pages = 1
        while page <= total_pages and seen < _MAX_FETCH_POSTS:
            res = endpoints.list_posts(page=page, limit=_FETCH_LIMIT) or {}
            data = res.get("data", {}) or {}
            raw = data.get("posts", []) or []
            try:
                total_pages = int(data.get("totalPages") or page)
            except (TypeError, ValueError):
                total_pages = page
            if not raw:
                break
            for entry in raw:
                seen += 1
                post = entry.get("post", {}) or {}
                pid = post.get("id")
                if pid is None:
                    continue
                title = str(
                    post.get("postTitle") or post.get("prompt") or "Untitled"
                )[:48]
                view = _view_for(post.get("generationType"), title)
                if view is None:
                    continue
                ps = entry.get("presignedUrls", {}) or {}
                buckets[view].append(
                    {
                        "id": pid,
                        "title": title,
                        "status": post.get("status") or "new",
                        "thumb_url": ps.get("thumbnailUrl") or ps.get("imageUrl"),
                    }
                )
            page += 1
        mainthread.run_on_main_thread(lambda b=buckets: _apply_results(b))
    except ApiError as exc:
        mainthread.run_on_main_thread(lambda e=exc: _set_error(e.message))
    except Exception as exc:  # noqa: BLE001
        mainthread.run_on_main_thread(lambda e=exc: _set_error(repr(exc)))


def _apply_results(buckets):
    """Main thread: store each view's list (page-anchored), prune caches, load
    visible-page thumbnails, re-arm auto-refresh."""
    global _loading, _fetch_active, _refetch_requested
    _fetch_active = False
    if not _alive:
        return
    live_ids = set()
    visible = []
    for key in _VIEW_KEYS:
        new_list = buckets.get(key, [])
        anchor = _first_visible_id(_views[key], _pages[key])
        _views[key] = new_list
        _pages[key] = _page_for_id(new_list, anchor, _pages[key])
        live_ids |= {p["id"] for p in new_list}
        visible += _page_slice(new_list, _pages[key])
    _loading = False
    _prune_caches(live_ids)
    mainthread.tag_redraw_all()
    _load_thumbs(visible)
    if _refetch_requested:
        # A job was submitted while this fetch was running — it may predate the
        # new post, so fetch once more to pick it up.
        _refetch_requested = False
        _start_fetch(quiet=True)
        return
    _maybe_schedule_auto_refresh()


def _prune_caches(live_ids):
    coll = _thumb_coll
    for pid in list(_thumb_files.keys()):
        if pid not in live_ids:
            _thumb_files.pop(pid, None)
            key = str(pid)
            if coll is not None and key in coll:
                del coll[key]
    for pid in list(_formats.keys()):
        if pid not in live_ids:
            _formats.pop(pid, None)
    _thumb_pending.intersection_update(live_ids)


# ── lazy thumbnails (only for the visible page) ───────────────────────


def _load_thumbs(posts):
    todo = []
    for p in posts:
        pid = p["id"]
        if p.get("thumb_url") and pid not in _thumb_files and pid not in _thumb_pending:
            _thumb_pending.add(pid)
            todo.append((pid, p["thumb_url"]))
    if not todo:
        return
    threading.Thread(
        target=_thumb_worker, args=(todo,), daemon=True, name="Alpha3D-thumbs"
    ).start()


def _thumb_worker(todo):
    new_thumbs = {}
    for pid, url in todo:
        try:
            dest = os.path.join(tempfile.gettempdir(), f"alpha3d_thumb_{pid}.img")
            endpoints.download_file(url, dest)
            new_thumbs[pid] = dest
        except Exception:  # noqa: BLE001
            pass
    attempted = [pid for pid, _ in todo]
    mainthread.run_on_main_thread(
        lambda t=new_thumbs, a=attempted: _apply_thumbs(t, a)
    )


def _apply_thumbs(new_thumbs, attempted_ids):
    if not _alive:
        return
    coll = _ensure_thumb_coll()
    for pid, path in new_thumbs.items():
        _thumb_files[pid] = path
        key = str(pid)
        if key in coll:
            del coll[key]
        try:
            coll.load(key, path, "IMAGE")
        except Exception:  # noqa: BLE001
            pass
    for pid in attempted_ids:
        _thumb_pending.discard(pid)
    mainthread.tag_redraw_all()


# ── pagination (main thread) ──────────────────────────────────────────


def _change_page(view, delta):
    if view not in _views:
        return
    _pages[view] = _clamp_page(_pages[view] + delta, len(_views[view]))
    _load_thumbs(get_page(view))
    mainthread.tag_redraw_all()


# ── auto-refresh while jobs are in progress (main thread) ────────────


def _maybe_schedule_auto_refresh():
    global _auto_pending
    if not _alive or _auto_pending or not _has_in_progress():
        return
    _auto_pending = True
    bpy.app.timers.register(_auto_refresh_tick, first_interval=_AUTO_REFRESH_SECONDS)


def _auto_refresh_tick():
    global _auto_pending
    _auto_pending = False
    if _alive and is_connected() and _has_in_progress():
        _start_fetch(quiet=True)
    return None


# ── import a completed post (with download progress) ──────────────────


def _report_progress_pct(post_id, pct):
    """Worker thread. Throttle to integer-percent changes so we don't flood the
    main-thread queue with redraws."""
    if _progress_throttle.get(post_id) == pct:
        return
    _progress_throttle[post_id] = pct
    mainthread.run_on_main_thread(lambda p=post_id, v=pct: _set_import_progress(p, v))


def _report_progress(post_id, downloaded, total):
    """Worker thread (from download_file). Map bytes -> integer percent."""
    if total and total > 0:
        _report_progress_pct(post_id, min(100, int(downloaded * 100 / total)))
    else:
        _report_progress_pct(post_id, -1)


def _run_import(post_id, fmt):
    """Worker: resolve the post's available formats, then either import the
    chosen one, auto-import the only one available, or reveal the chooser."""
    try:
        detail = endpoints.get_post(post_id) or {}
        obj_files = (
            ((detail.get("data", {}) or {}).get("downloadUrls", {}) or {}).get(
                "objFiles", {}
            )
            or {}
        )

        # Segmentation posts ship N parts — import ALL of them under one parent
        # (like the segmentation flow), not just the part_0 mirror at glb.
        part_urls = _segment_part_urls(obj_files)
        if part_urls:
            post_obj = (detail.get("data", {}) or {}).get("post", {}) or {}
            parent_name = (
                post_obj.get("postTitle") or post_obj.get("prompt")
                or f"Model {post_id}"
            )
            _import_all_parts(post_id, part_urls, parent_name)
            return

        available = _mesh_formats_from_objfiles(obj_files)
        if not available:
            raise ApiError(0, "This model has no importable mesh.")

        mainthread.run_on_main_thread(
            lambda pid=post_id, a=list(available): _set_formats(pid, a)
        )

        chosen = (fmt or "").lower()
        if not chosen:
            if len(available) > 1:
                _set_action_async(
                    "Multiple formats available — choose one to import.", post_id
                )
                # Not importing yet — release the guard so the format click works.
                mainthread.run_on_main_thread(
                    lambda pid=post_id: _importing.discard(pid)
                )
                return
            chosen = available[0]
        elif chosen not in available:
            raise ApiError(0, f"{chosen.upper()} is not available for this model.")

        url = _url_for_format(obj_files, chosen)
        if not url:
            raise ApiError(0, f"No {chosen.upper()} file to import.")
        dest = os.path.join(
            tempfile.gettempdir(), f"alpha3d_lib_{post_id}.{chosen}"
        )
        # Show the download percentage on the button from here on.
        _progress_throttle.pop(post_id, None)
        mainthread.run_on_main_thread(lambda pid=post_id: _set_import_progress(pid, 0))
        endpoints.download_file(
            url, dest,
            progress_cb=lambda d, t, pid=post_id: _report_progress(pid, d, t),
        )
        if chosen in ("glb", "gltf"):
            trimmed, declared, actual = glbutil.sanitize_glb(dest)
            print(
                f"[Alpha3D] GLB post {post_id}: declared={declared} "
                f"actual={actual} trimmed={trimmed}"
            )
        mainthread.run_on_main_thread(
            lambda p=dest, pid=post_id, c=chosen: _do_import(p, pid, c)
        )
    except ApiError as exc:
        _progress_throttle.pop(post_id, None)
        mainthread.run_on_main_thread(lambda pid=post_id: _clear_import_progress(pid))
        _set_action_async(f"Import failed: {exc.message}", post_id)
    except Exception as exc:  # noqa: BLE001
        _progress_throttle.pop(post_id, None)
        mainthread.run_on_main_thread(lambda pid=post_id: _clear_import_progress(pid))
        _set_action_async(f"Import failed: {exc!r}", post_id)


def _do_import(filepath, post_id, fmt):
    """Main thread: import the downloaded mesh with the format's importer."""
    if not _alive:
        return
    _import_progress.pop(post_id, None)
    _progress_throttle.pop(post_id, None)
    _importing.discard(post_id)  # release the dedup guard
    exists = os.path.isfile(filepath)
    size = os.path.getsize(filepath) if exists else -1
    print(
        f"[Alpha3D] import post {post_id}: fmt={fmt} file={filepath} "
        f"exists={exists} bytes={size}"
    )
    try:
        _import_file(filepath, fmt)
    except Exception as exc:  # noqa: BLE001
        print(f"[Alpha3D] import FAILED for post {post_id}: {exc!r}")
        _set_action(f"Import failed: {exc!r}", post_id)
        notice.show(f"Import failed: {exc!r}", icon="ERROR")
        return
    print(f"[Alpha3D] import OK for post {post_id}")
    _set_action(f"Imported model #{post_id} ({fmt.upper()}) into the scene.", post_id)
    notice.show(f"Model #{post_id} imported.")


def _import_all_parts(post_id, part_urls, parent_name):
    """Worker: download every segmentation part (combined progress on the
    button), then import them all (grouped under one parent) on the main
    thread. Raises on download failure so the caller's handler clears progress
    + reports it."""
    _progress_throttle.pop(post_id, None)
    mainthread.run_on_main_thread(lambda pid=post_id: _set_import_progress(pid, 0))
    total = len(part_urls)
    paths = []
    for i, purl in enumerate(part_urls):
        dest = os.path.join(tempfile.gettempdir(), f"alpha3d_lib_{post_id}_p{i}.glb")
        endpoints.download_file(
            purl, dest,
            progress_cb=lambda d, t, i=i: _report_progress_pct(
                post_id,
                min(100, int(((i + ((d / t) if (t and t > 0) else 0)) / total) * 100)),
            ),
        )
        trimmed, declared, actual = glbutil.sanitize_glb(dest)
        print(
            f"[Alpha3D] segment part {i} (post {post_id}): declared={declared} "
            f"actual={actual} trimmed={trimmed}"
        )
        paths.append(dest)
    mainthread.run_on_main_thread(
        lambda p=list(paths), pid=post_id, n=parent_name: _do_import_parts(p, pid, n)
    )


def _do_import_parts(paths, post_id, parent_name):
    """Main thread: import every downloaded segmentation part, grouped under one
    parent Empty so they read as a single model with parts."""
    if not _alive:
        return
    _import_progress.pop(post_id, None)
    _progress_throttle.pop(post_id, None)
    _importing.discard(post_id)  # release the dedup guard
    try:
        imported = sceneimport.import_parts_under_parent(paths, parent_name)
    except Exception as exc:  # noqa: BLE001
        print(f"[Alpha3D] segment import FAILED for post {post_id}: {exc!r}")
        _set_action(f"Import failed: {exc!r}", post_id)
        notice.show(f"Import failed: {exc!r}", icon="ERROR")
        return
    if imported == 0:
        _set_action("Nothing was imported.", post_id)
        return
    print(f"[Alpha3D] imported {imported} segment parts for post {post_id}")
    _set_action(f"Imported model #{post_id} — {imported} parts into the scene.", post_id)
    notice.show(f"Model #{post_id} imported ({imported} parts).")


def _import_file(filepath, fmt):
    """Run the format's importer under a valid 3D-view context (operators from
    the timer drain can otherwise hit a context error)."""
    mainthread.run_in_view3d_context(lambda: _dispatch_import(filepath, fmt))


def _dispatch_import(filepath, fmt):
    fmt = (fmt or "glb").lower()
    if fmt in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif fmt == "obj":
        if "obj_import" in dir(bpy.ops.wm):
            bpy.ops.wm.obj_import(filepath=filepath)
        else:
            raise RuntimeError("OBJ importer unavailable in this Blender build.")
    elif fmt == "fbx":
        if "fbx" in dir(bpy.ops.import_scene):
            bpy.ops.import_scene.fbx(filepath=filepath)
        else:
            raise RuntimeError(
                "FBX importer is off. Enable 'Import-Export: FBX format' in "
                "Preferences > Add-ons, or import the GLB instead."
            )
    elif fmt == "stl":
        if "stl_import" in dir(bpy.ops.wm):
            bpy.ops.wm.stl_import(filepath=filepath)
        else:
            raise RuntimeError("STL importer unavailable in this Blender build.")
    else:
        raise ValueError(f"Unsupported format: {fmt}")


# ── operators ──────────────────────────────────────────────────────────


class ALPHA3D_OT_library_refresh(bpy.types.Operator):
    bl_idname = "alpha3d.library_refresh"
    bl_label = "Refresh"
    bl_description = "Reload your Alpha3D generations"

    def execute(self, context):
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        _start_fetch()
        return {"FINISHED"}


class ALPHA3D_OT_library_page(bpy.types.Operator):
    bl_idname = "alpha3d.library_page"
    bl_label = "Page"
    bl_description = "Show the previous / next page"

    view: bpy.props.StringProperty(default="assets")
    delta: bpy.props.IntProperty(default=1)

    def execute(self, context):
        _change_page(self.view, self.delta)
        return {"FINISHED"}


class ALPHA3D_OT_library_import(bpy.types.Operator):
    bl_idname = "alpha3d.library_import"
    bl_label = "Import to scene"
    bl_description = (
        "Download this model and import it into the scene. If it has several "
        "formats, you'll be able to pick which one"
    )

    post_id: bpy.props.IntProperty(default=0)
    fmt: bpy.props.StringProperty(default="")

    def execute(self, context):
        if not is_connected():
            self.report({"ERROR"}, "Connect your Alpha3D account first.")
            return {"CANCELLED"}
        if self.post_id <= 0:
            self.report({"ERROR"}, "No model selected.")
            return {"CANCELLED"}
        # Dedup: a second click (e.g. before the button turns into a progress
        # bar) would spawn a second worker downloading to the SAME temp path,
        # and the two would clobber each other mid-write -> "Bad GLB". execute()
        # runs serially on the main thread, so this check+add is race-free.
        if self.post_id in _importing:
            self.report({"INFO"}, "Already importing this model.")
            return {"CANCELLED"}
        _importing.add(self.post_id)
        label = f" as {self.fmt.upper()}" if self.fmt else ""
        _set_action(f"Importing model #{self.post_id}{label}...", self.post_id)
        threading.Thread(
            target=_run_import,
            args=(self.post_id, self.fmt),
            daemon=True,
            name="Alpha3D-libimport",
        ).start()
        return {"FINISHED"}


classes = (
    ALPHA3D_OT_library_refresh,
    ALPHA3D_OT_library_page,
    ALPHA3D_OT_library_import,
)


def register():
    global _alive, _fetch_active, _refetch_requested, _auto_pending, _ever_fetched
    global _views, _pages, _error, _action, _action_post_id
    global _thumb_files, _thumb_pending, _formats, _import_progress, _progress_throttle
    global _importing
    _alive = True
    _fetch_active = False
    _refetch_requested = False
    _auto_pending = False
    _ever_fetched = False
    _views = {k: [] for k in _VIEW_KEYS}
    _pages = {k: 0 for k in _VIEW_KEYS}
    _error = ""
    _action = ""
    _action_post_id = None
    _thumb_files = {}
    _thumb_pending = set()
    _formats = {}
    _import_progress = {}
    _progress_throttle = {}
    _importing = set()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _thumb_coll, _views, _pages, _thumb_files, _thumb_pending, _formats
    global _import_progress, _progress_throttle, _auto_pending, _alive, _fetch_active
    global _refetch_requested, _importing
    _alive = False
    _fetch_active = False
    _refetch_requested = False
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if bpy.app.timers.is_registered(_auto_refresh_tick):
        bpy.app.timers.unregister(_auto_refresh_tick)
    _auto_pending = False
    _views = {k: [] for k in _VIEW_KEYS}
    _pages = {k: 0 for k in _VIEW_KEYS}
    _thumb_files = {}
    _thumb_pending = set()
    _formats = {}
    _import_progress = {}
    _progress_throttle = {}
    _importing = set()
    if _thumb_coll is not None:
        bpy.utils.previews.remove(_thumb_coll)
        _thumb_coll = None
