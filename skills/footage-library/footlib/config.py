"""Paths and tunables. Everything can be overridden with FOOTLIB_* env vars."""
import os
from pathlib import Path

# The library (DB + thumbnail cache) lives outside the plugin so updates never touch it.
LIBRARY_HOME = Path(os.environ.get("FOOTLIB_HOME", "~/.footlib")).expanduser()
DB_PATH = LIBRARY_HOME / "footlib.db"
THUMB_DIR = LIBRARY_HOME / "cache" / "thumbs"
SHEET_DIR = LIBRARY_HOME / "cache" / "sheets"
PAGE_DIR = LIBRARY_HOME / "cache" / "pages"

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm", ".mxf", ".3gp"}

# Keyframes: one every N seconds, plus one at the middle of each detected scene.
KEYFRAME_INTERVAL = float(os.environ.get("FOOTLIB_KEYFRAME_INTERVAL", "2.0"))
# Keyframes closer than this to an existing one are skipped (avoids near-duplicates).
KEYFRAME_MIN_GAP = 0.75
THUMB_WIDTH = 384

WHISPER_MODEL = os.environ.get("FOOTLIB_WHISPER_MODEL", "small")

# SigLIP via open_clip. ViT-B-16 is ~800 MB and fast on MPS; swap for
# ViT-SO400M-14-SigLIP-384 if you want better recall and have the disk.
CLIP_MODEL = os.environ.get("FOOTLIB_CLIP_MODEL", "ViT-B-16-SigLIP")
CLIP_PRETRAINED = os.environ.get("FOOTLIB_CLIP_PRETRAINED", "webli")
EMBED_DIM = 768


def ensure_dirs():
    for d in (LIBRARY_HOME, THUMB_DIR, SHEET_DIR, PAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
