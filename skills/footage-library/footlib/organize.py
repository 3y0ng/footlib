"""Organised views of the library as folders of symlinks. Originals are never moved or copied.
Delete the view folder any time; rebuild it with the same command."""
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import db


def _safe(name: str) -> str:
    return re.sub(r"[/:\\\\]+", "-", name).strip() or "untitled"


def groups(con, by: str):
    """by='date' -> YYYY/YYYY-MM-DD; by='<namespace>' (e.g. 'project', 'shot', 'person') -> tag values;
    by='tag' -> every tag."""
    out = defaultdict(list)
    for c in con.execute("SELECT c.id, c.created_at, min(f.mtime) AS mtime FROM clips c "
                         "LEFT JOIN files f ON f.clip_id = c.id GROUP BY c.id"):
        if by == "date":
            # Capture date from metadata; fall back to the file's modified date (downloads, exports).
            d = (c["created_at"] or "")[:10]
            if not d and c["mtime"]:
                d = datetime.fromtimestamp(c["mtime"]).strftime("%Y-%m-%d")
            d = d or "unknown-date"
            out[f"{d[:4]}/{d}" if d != "unknown-date" else d].append(c["id"])
            continue
        tags = [r["tag"] for r in con.execute("SELECT tag FROM tags WHERE clip_id=?", (c["id"],))]
        if by == "tag":
            for t in tags or ["untagged"]:
                out[t].append(c["id"])
        else:
            vals = [t.split(":", 1)[1] for t in tags if t.startswith(by + ":")]
            for v in vals or [f"no-{by}"]:
                out[v].append(c["id"])
    return out


def build(con, by: str, into: str, log=print):
    root = Path(into).expanduser()
    made = 0
    for group, ids in sorted(groups(con, by).items()):
        folder = root / Path(*[_safe(p) for p in group.split("/")])
        folder.mkdir(parents=True, exist_ok=True)
        for cid in ids:
            path, online = db.clip_path(con, cid)
            if not path:
                continue
            link = folder / os.path.basename(path)
            if link.exists() or link.is_symlink():
                if os.path.realpath(link) == os.path.realpath(path):
                    continue
                link = folder / f"{cid}_{os.path.basename(path)}"
                if link.is_symlink():
                    continue
            link.symlink_to(path)  # dangling while the drive is unplugged; works again when it's back
            made += 1
    log(f"  {made} links under {root}")
    return made
