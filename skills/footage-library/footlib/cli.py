"""footlib CLI. Every stage is incremental and runnable on its own."""
import argparse
import json
import os
import shutil
import sys

from . import config, db


def cmd_doctor(con, a):
    """Check the machine can run everything."""
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"  {tool:10s} {'ok  ' + found if found else 'MISSING (brew install ffmpeg)'}")
        ok &= bool(found)
    print(f"  sqlite-vec ok  {con.execute('select vec_version()').fetchone()[0]}")
    try:
        import torch
        print(f"  torch      ok  {torch.__version__}, device={'mps' if torch.backends.mps.is_available() else 'cpu'}")
    except Exception as e:
        print(f"  torch      FAILED {e}")
        ok = False
    print(f"  library    {config.LIBRARY_HOME}")
    print("ready" if ok else "fix the items above")


def cmd_ingest(con, a):
    from .ingest import ingest
    print(f"ingest → {config.DB_PATH}")
    print("  ", ingest(con, a.folders, full_hash=a.full_hash))


def cmd_transcribe(con, a):
    from .transcribe import transcribe
    print(f"  transcribed {transcribe(con, a.model, a.force, language=a.language)} clips")


def cmd_embed(con, a):
    from .embed import embed
    print(f"  embedded {embed(con)} clips")


def cmd_index(con, a):
    cmd_ingest(con, a)
    if not a.no_transcribe:
        cmd_transcribe(con, a)
    cmd_embed(con, a)


def cmd_search(con, a):
    from .search import search
    res = search(con, " ".join(a.query), a.limit, a.mode, a.year, a.tag or ())
    if a.json:
        print(json.dumps(res, indent=2))
        return
    if not res:
        print("no results")
    for i, r in enumerate(res, 1):
        flag = "" if r["online"] else "  [OFFLINE: plug in the drive]"
        print(f"{i:2d}. {os.path.basename(r['file'])}  {r['in_tc']} → {r['out_tc']}  "
              f"[{'+'.join(r['sources'])}] {r['score']:.3f}{flag}")
        if r["snippet"]:
            print(f"      “{r['snippet'][:110]}”")
        print(f"      {r['file']}")


def cmd_status(con, a):
    q = lambda s: con.execute(s).fetchone()[0]
    print(f"library: {config.LIBRARY_HOME}")
    print(f"clips {q('SELECT count(*) FROM clips')}  files {q('SELECT count(*) FROM files')}  "
          f"keyframes {q('SELECT count(*) FROM keyframes')}  segments {q('SELECT count(*) FROM segments')}  "
          f"tagged {q('SELECT count(DISTINCT clip_id) FROM tags')}")
    print(f"pending: transcribe {q('SELECT count(*) FROM clips WHERE has_audio=1 AND transcribed_at IS NULL')}  "
          f"embed {q('SELECT count(*) FROM clips WHERE embedded_at IS NULL')}  "
          f"untagged {q('SELECT count(*) FROM clips WHERE id NOT IN (SELECT clip_id FROM tags)')}")
    for v in con.execute("SELECT v.*, count(f.id) n FROM volumes v LEFT JOIN files f ON f.volume_uuid=v.uuid GROUP BY v.uuid"):
        state = "online" if os.path.exists(v["last_mount"]) else "OFFLINE"
        print(f"drive {v['name']} ({state}) {v['n']} files")


def cmd_clips(con, a):
    """List clips with contact sheet, transcript and tags."""
    for c in con.execute("SELECT * FROM clips ORDER BY created_at"):
        path, online = db.clip_path(con, c["id"])
        if a.folder and not (path or "").startswith(os.path.abspath(os.path.expanduser(a.folder))):
            continue
        tags = [r["tag"] for r in con.execute("SELECT tag FROM tags WHERE clip_id=?", (c["id"],))]
        if a.untagged and tags:
            continue
        text = " ".join(r["text"] for r in con.execute("SELECT text FROM segments WHERE clip_id=? ORDER BY start", (c["id"],)))
        row = {"clip_id": c["id"], "file": path, "online": online, "duration": round(c["duration"], 2),
               "created_at": c["created_at"], "res": f"{c['width']}x{c['height']}", "fps": c["fps"],
               "sheet": str(config.SHEET_DIR / f"{c['hash']}.jpg"), "transcript": text, "caption": c["caption"], "tags": tags}
        print(json.dumps(row) if a.json else
              f"{c['id']:4d} {os.path.basename(path or ''):40s} {c['duration']:7.1f}s {row['res']:>9s}  {', '.join(tags)}")


def cmd_pages(con, a):
    """Overview pages (one row per clip) for tagging in batches."""
    from .pages import build
    pages = build(con, a.per_page, a.untagged, a.folder)
    print(f"  {len(pages)} pages, {sum(len(p['clips']) for p in pages)} clips → {config.PAGE_DIR}")
    print(f"  index: {config.PAGE_DIR / 'pages.json'}")


def cmd_annotate(con, a):
    """Import captions/tags/moments JSON: [{file|clip_id, caption, tags:[...], moments:[{start,end,text}]}]."""
    items = json.load(open(a.file))
    done = 0
    for it in items:
        if "clip_id" in it:
            cid = it["clip_id"]
        else:
            r = con.execute("SELECT clip_id FROM files WHERE path=? OR path LIKE ?",
                            (it["file"], "%/" + os.path.basename(it["file"]))).fetchone()
            if not r:
                print(f"  not in library: {it['file']}", file=sys.stderr)
                continue
            cid = r["clip_id"]
        src = it.get("source", a.source)
        if "caption" in it:
            con.execute("UPDATE clips SET caption=? WHERE id=?", (it["caption"], cid))
        con.execute("DELETE FROM tags WHERE clip_id=? AND source=?", (cid, src))
        con.executemany("INSERT OR REPLACE INTO tags VALUES(?,?,?)", [(cid, t, src) for t in it.get("tags", [])])
        if "moments" in it:
            con.execute("DELETE FROM moments WHERE clip_id=? AND source=?", (cid, src))
            con.executemany("INSERT INTO moments(clip_id,start,end,text,source) VALUES(?,?,?,?,?)",
                            [(cid, m["start"], m["end"], m["text"], src) for m in it["moments"]])
        done += 1
    con.commit()
    print(f"  annotated {done} clips")


def cmd_tag(con, a):
    """Add or remove tags on one clip by hand (source=user, kept separate from auto tags)."""
    for t in a.add or []:
        con.execute("INSERT OR REPLACE INTO tags VALUES(?,?, 'user')", (a.clip_id, t))
    for t in a.remove or []:
        con.execute("DELETE FROM tags WHERE clip_id=? AND tag=?", (a.clip_id, t))
    con.commit()
    print(", ".join(r["tag"] for r in con.execute("SELECT tag FROM tags WHERE clip_id=?", (a.clip_id,))))


def cmd_organize(con, a):
    """Folders of symlinks grouped by date or a tag namespace. Never moves originals."""
    from .organize import build
    build(con, a.by, a.into)


def main(argv=None):
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser(prog="footlib", description="Local searchable footage library")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check ffmpeg, sqlite-vec, torch/MPS")
    s = sub.add_parser("ingest", help="hash, probe, scenes, keyframes, thumbnails")
    s.add_argument("folders", nargs="+")
    s.add_argument("--full-hash", action="store_true", help="hash whole files (slow) instead of a sampled hash")
    s = sub.add_parser("index", help="ingest + transcribe + embed: the one command for a new folder or drive")
    s.add_argument("folders", nargs="+")
    s.add_argument("--full-hash", action="store_true")
    s.add_argument("--model", default=None, help="whisper model (default small)")
    s.add_argument("--language", default=None, help="force transcript language, e.g. en")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-transcribe", action="store_true")
    s = sub.add_parser("transcribe", help="faster-whisper transcripts with word timestamps")
    s.add_argument("--model", default=None)
    s.add_argument("--language", default=None)
    s.add_argument("--force", action="store_true")
    sub.add_parser("embed", help="SigLIP keyframe embeddings")
    s = sub.add_parser("search", help="natural-language visual + transcript + tag search")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=10)
    s.add_argument("--mode", choices=["hybrid", "visual", "speech", "notes"], default="hybrid")
    s.add_argument("--year")
    s.add_argument("--tag", action="append")
    s.add_argument("--json", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("clips")
    s.add_argument("--folder")
    s.add_argument("--untagged", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("pages", help="overview pages for batch tagging")
    s.add_argument("--per-page", type=int, default=6)
    s.add_argument("--untagged", action="store_true")
    s.add_argument("--folder")
    s = sub.add_parser("annotate", help="import captions/tags/moments JSON")
    s.add_argument("file")
    s.add_argument("--source", default="vlm")
    s = sub.add_parser("tag", help="add/remove tags on a clip by hand")
    s.add_argument("clip_id", type=int)
    s.add_argument("--add", action="append")
    s.add_argument("--remove", action="append")
    s = sub.add_parser("organize", help="symlink folders grouped by date or tag namespace")
    s.add_argument("--by", default="date", help="date | tag | <namespace> e.g. project, shot, person, setting")
    s.add_argument("--into", required=True)

    a = p.parse_args(argv)
    con = db.connect()
    globals()[f"cmd_{a.cmd}"](con, a)


if __name__ == "__main__":
    main()
