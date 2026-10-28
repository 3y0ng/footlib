"""Walk folders → hash (cached by path/size/mtime) → dedupe → probe → keyframes.
Originals are only ever read."""
import hashlib
import os
import sys
from datetime import datetime, timezone

from . import config, keyframes, probe, volumes


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: str, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def quick_hash(path: str, size: int, sample: int = 1 << 20) -> str:
    """Size + three 1 MB samples (start, middle, end). Reads ~3 MB instead of the whole file,
    which matters on big spinning drives. Prefixed so it never collides with a full hash."""
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        for off in (0, max(size // 2 - sample // 2, 0), max(size - sample, 0)):
            f.seek(off)
            h.update(f.read(sample))
    return "q" + h.hexdigest()[:63]


def walk(folders):
    for folder in folders:
        folder = os.path.abspath(os.path.expanduser(folder))
        if os.path.isfile(folder):
            yield folder
            continue
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in sorted(files):
                if not name.startswith(".") and os.path.splitext(name)[1].lower() in config.VIDEO_EXTS:
                    yield os.path.join(root, name)


def file_hash(con, path: str, st, full: bool = False) -> str:
    row = con.execute("SELECT hash, size, mtime FROM files WHERE path=?", (path,)).fetchone()
    if row and row["hash"] and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
        return row["hash"]
    return sha256(path) if full else quick_hash(path, st.st_size)


def ingest(con, folders, log=print, full_hash=False):
    stats = {"seen": 0, "new": 0, "dupes": 0, "skipped": 0, "errors": 0}
    paths = list(walk(folders))
    log(f"  found {len(paths)} video files")
    for n, path in enumerate(paths, 1):
        stats["seen"] += 1
        try:
            st = os.stat(path)
            if st.st_size == 0:
                stats["skipped"] += 1
                continue
            h = file_hash(con, path, st, full_hash)
            vuuid, vname, vmount = volumes.for_path(path)
            con.execute("INSERT INTO volumes(uuid, name, last_mount) VALUES(?,?,?) "
                        "ON CONFLICT(uuid) DO UPDATE SET name=excluded.name, last_mount=excluded.last_mount",
                        (vuuid, vname, vmount))

            clip = con.execute("SELECT id, ingested_at FROM clips WHERE hash=?", (h,)).fetchone()
            if clip is None:
                meta = probe.probe(path)
                cur = con.execute(
                    "INSERT INTO clips(hash,size,duration,width,height,fps,vcodec,acodec,has_audio,"
                    "created_at,gps_lat,gps_lon,device) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h, st.st_size, meta["duration"], meta["width"], meta["height"], meta["fps"], meta["vcodec"],
                     meta["acodec"], meta["has_audio"], meta["created_at"], meta["gps_lat"], meta["gps_lon"],
                     meta["device"]))
                clip_id, done = cur.lastrowid, None
                stats["new"] += 1
            else:
                clip_id, done = clip["id"], clip["ingested_at"]
                known = con.execute("SELECT 1 FROM files WHERE clip_id=? AND path!=?", (clip_id, path)).fetchone()
                if known and not con.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone():
                    stats["dupes"] += 1
                    log(f"  [{n}/{len(paths)}] dupe  {path}")

            con.execute(
                "INSERT INTO files(clip_id,path,volume_uuid,size,mtime,hash,last_seen) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET clip_id=excluded.clip_id, volume_uuid=excluded.volume_uuid, "
                "size=excluded.size, mtime=excluded.mtime, hash=excluded.hash, last_seen=excluded.last_seen",
                (clip_id, path, vuuid, st.st_size, st.st_mtime, h, now()))

            if not done:
                analyse(con, clip_id, path, h)
                log(f"  [{n}/{len(paths)}] ok    {os.path.basename(path)}")
            con.commit()
        except Exception as e:
            con.rollback()
            stats["errors"] += 1
            print(f"  ERROR {path}: {e}", file=sys.stderr)
    return stats


def analyse(con, clip_id, path, h):
    duration = con.execute("SELECT duration FROM clips WHERE id=?", (clip_id,)).fetchone()["duration"]
    scenes = keyframes.detect_scenes(path, duration)
    con.execute("DELETE FROM scenes WHERE clip_id=?", (clip_id,))
    con.executemany("INSERT INTO scenes VALUES(?,?,?,?)", [(clip_id, i, a, b) for i, (a, b) in enumerate(scenes)])

    frames = keyframes.extract_keyframes(path, h, keyframes.plan_keyframes(duration, scenes))
    old = [r["id"] for r in con.execute("SELECT id FROM keyframes WHERE clip_id=?", (clip_id,))]
    if old:
        con.executemany("DELETE FROM keyframe_vec WHERE rowid=?", [(i,) for i in old])
        con.execute("DELETE FROM keyframes WHERE clip_id=?", (clip_id,))
        con.execute("UPDATE clips SET embedded_at=NULL WHERE id=?", (clip_id,))
    con.executemany("INSERT INTO keyframes(clip_id,t,kind,scene_idx,thumb) VALUES(?,?,?,?,?)",
                    [(clip_id, t, k, i, p) for t, k, i, p in frames])

    sheet = config.SHEET_DIR / f"{h}.jpg"
    if frames:
        keyframes.contact_sheet([(t, p) for t, _, _, p in frames], sheet,
                                title=f"{os.path.basename(path)}  {duration:.1f}s  scenes={len(scenes)}")
    con.execute("UPDATE clips SET ingested_at=? WHERE id=?", (now(), clip_id))
