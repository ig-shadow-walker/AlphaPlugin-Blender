"""GLB file helpers (pure stdlib — no bpy, safe on worker threads)."""

import os
import struct

_GLB_MAGIC = b"glTF"


def sanitize_glb(path):
    """Make a downloaded .glb importable by Blender's strict glTF loader.

    A GLB's 12-byte header is: magic 'glTF' (4) | version (4) | total length
    (4, little-endian) = the whole file's byte length. Some producers/CDNs
    emit or serve a GLB with EXTRA bytes past that declared length (trailing
    padding, a stray newline, etc.). three.js reads exactly `length` bytes and
    ignores the rest, so it loads on the web; Blender compares the declared
    length to the file size and rejects it with
    "Bad GLB: file size doesn't match". If the file is a GLB whose actual size
    EXCEEDS its declared length, truncate it to the declared length so Blender
    accepts it.

    Returns (truncated, declared_length, actual_size) for logging. Only ever
    SHRINKS an oversized GLB; never pads, never touches non-GLB files, and
    never raises (returns the size info it could gather).
    """
    try:
        actual = os.path.getsize(path)
    except OSError:
        return (False, None, None)
    try:
        with open(path, "rb") as f:
            header = f.read(12)
    except OSError:
        return (False, None, actual)
    if len(header) < 12 or header[:4] != _GLB_MAGIC:
        return (False, None, actual)  # not a GLB — leave it alone
    declared = struct.unpack("<I", header[8:12])[0]
    if declared and actual > declared:
        try:
            with open(path, "r+b") as f:
                f.truncate(declared)
            return (True, declared, actual)
        except OSError:
            return (False, declared, actual)
    return (False, declared, actual)
