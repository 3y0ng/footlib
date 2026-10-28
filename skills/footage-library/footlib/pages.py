"""Overview pages for tagging in batches: one row per clip, up to 7 timestamped frames each.
Claude (or a person) looks at a page and writes captions/tags/moments for every clip on it."""
import json
import os

from PIL import Image, ImageDraw, ImageFont

from . import config, db

W, H, PER_ROW = 150, 267, 7


def _font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size)
    except Exception:
        return ImageFont.load_default()


def build(con, per_page=6, untagged=False, folder=None):
    q = "SELECT id, duration FROM clips WHERE ingested_at IS NOT NULL"
    if untagged:
        q += " AND id NOT IN (SELECT DISTINCT clip_id FROM tags)"
    rows = con.execute(q + " ORDER BY created_at, id").fetchall()
    clips = []
    for r in rows:
        path, _ = db.clip_path(con, r["id"])
        if folder and not (path or "").startswith(os.path.abspath(os.path.expanduser(folder))):
            continue
        clips.append((r["id"], r["duration"], path))

    config.PAGE_DIR.mkdir(parents=True, exist_ok=True)
    for old in config.PAGE_DIR.glob("page_*.jpg"):
        old.unlink()
    small, big = _font(14), _font(15)
    pages = []
    for start in range(0, len(clips), per_page):
        chunk = clips[start:start + per_page]
        sheet = Image.new("RGB", (W * PER_ROW + 170, H * len(chunk)), "black")
        d = ImageDraw.Draw(sheet)
        for r, (cid, dur, path) in enumerate(chunk):
            ks = con.execute("SELECT t, thumb FROM keyframes WHERE clip_id=? ORDER BY t", (cid,)).fetchall()
            if len(ks) > PER_ROW:
                ks = [ks[round(i * (len(ks) - 1) / (PER_ROW - 1))] for i in range(PER_ROW)]
            name = os.path.basename(path or "")
            d.text((4, r * H + 4), f"#{cid}", fill="yellow", font=big)
            d.text((4, r * H + 24), name[:20], fill="white", font=small)
            d.text((4, r * H + 42), name[20:40], fill="white", font=small)
            d.text((4, r * H + 62), f"{dur:.1f}s", fill="cyan", font=small)
            for i, k in enumerate(ks):
                if not os.path.exists(k["thumb"]):
                    continue
                im = Image.open(k["thumb"]).convert("RGB")
                im.thumbnail((W, H))
                x = 170 + i * W
                sheet.paste(im, (x, r * H))
                d.rectangle([x, r * H, x + 52, r * H + 17], fill="black")
                d.text((x + 2, r * H + 1), f"{k['t']:.1f}", fill="yellow", font=small)
        out = config.PAGE_DIR / f"page_{start // per_page + 1:03d}.jpg"
        sheet.save(out, quality=82)
        pages.append({"page": str(out), "clips": [{"clip_id": c, "file": p, "duration": round(d_, 2)}
                                                   for c, d_, p in chunk]})
    (config.PAGE_DIR / "pages.json").write_text(json.dumps(pages, indent=1))
    return pages
