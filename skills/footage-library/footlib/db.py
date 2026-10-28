"""SQLite schema: clips (deduped by content hash), file locations, keyframes,
transcript segments/words (+FTS5), keyframe embeddings (sqlite-vec), tags."""
import sqlite3

import sqlite_vec

from . import config

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS volumes (
    uuid        TEXT PRIMARY KEY,
    name        TEXT,
    last_mount  TEXT
);

CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY,
    hash          TEXT UNIQUE NOT NULL,      -- sha256 of file contents
    size          INTEGER,
    duration      REAL,
    width         INTEGER,                   -- display width (rotation applied)
    height        INTEGER,
    fps           REAL,
    vcodec        TEXT,
    acodec        TEXT,
    has_audio     INTEGER,
    created_at    TEXT,                      -- capture time, ISO 8601
    gps_lat       REAL,
    gps_lon       REAL,
    device        TEXT,
    caption       TEXT,                      -- free-text description (VLM or human)
    ingested_at   TEXT,
    transcribed_at TEXT,
    embedded_at   TEXT
);

-- One clip can live in several places (SSD + iCloud export). Paths are kept
-- even when the drive is unplugged; `volume_uuid` says which drive to plug in.
CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY,
    clip_id      INTEGER REFERENCES clips(id),
    path         TEXT UNIQUE NOT NULL,
    volume_uuid  TEXT,
    size         INTEGER,
    mtime        REAL,
    hash         TEXT,
    last_seen    TEXT
);

CREATE TABLE IF NOT EXISTS keyframes (
    id         INTEGER PRIMARY KEY,
    clip_id    INTEGER REFERENCES clips(id),
    t          REAL NOT NULL,              -- seconds from clip start
    kind       TEXT,                       -- 'scene' | 'interval'
    scene_idx  INTEGER,
    thumb      TEXT                        -- path in local cache
);
CREATE INDEX IF NOT EXISTS keyframes_clip ON keyframes(clip_id, t);

CREATE TABLE IF NOT EXISTS scenes (
    clip_id  INTEGER REFERENCES clips(id),
    idx      INTEGER,
    start    REAL,
    end      REAL,
    PRIMARY KEY (clip_id, idx)
);

CREATE TABLE IF NOT EXISTS segments (
    id        INTEGER PRIMARY KEY,
    clip_id   INTEGER REFERENCES clips(id),
    start     REAL,
    end       REAL,
    text      TEXT,
    language  TEXT
);
CREATE TABLE IF NOT EXISTS words (
    segment_id INTEGER REFERENCES segments(id),
    clip_id    INTEGER,
    start      REAL,
    end        REAL,
    word       TEXT,
    prob       REAL
);
CREATE INDEX IF NOT EXISTS words_seg ON words(segment_id);
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='id', tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS tags (
    clip_id  INTEGER REFERENCES clips(id),
    tag      TEXT,                 -- e.g. 'shot:close', 'subject:speedmaster'
    source   TEXT,                 -- 'auto' | 'vlm' | 'user'
    PRIMARY KEY (clip_id, tag)
);

-- Described sub-ranges of a clip ("hands lift lid", 3.2-5.0s).
CREATE TABLE IF NOT EXISTS moments (
    id        INTEGER PRIMARY KEY,
    clip_id   INTEGER REFERENCES clips(id),
    start     REAL,
    end       REAL,
    text      TEXT,
    source    TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS keyframe_vec USING vec0(
    embedding float[{config.EMBED_DIM}] distance_metric=cosine
);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def clip_path(con, clip_id):
    """Best available path for a clip: an online copy if any, else the last known one."""
    import os
    rows = con.execute("SELECT path FROM files WHERE clip_id=? ORDER BY last_seen DESC", (clip_id,)).fetchall()
    for r in rows:
        if os.path.exists(r["path"]):
            return r["path"], True
    return (rows[0]["path"] if rows else None), False
