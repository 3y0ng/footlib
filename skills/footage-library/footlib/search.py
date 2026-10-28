"""One query → visual (SigLIP), transcript (FTS5) and notes (captions/moments) hits,
fused with reciprocal-rank fusion into moments: file + in/out timecode."""
import re
from dataclasses import dataclass, field

from . import config, db

STOP = {"a", "an", "the", "of", "at", "in", "on", "with", "and", "or", "to", "me", "my", "is", "someone", "anyone",
        "saying", "says", "said", "shot", "clip", "video", "footage", "where", "when", "some"}


@dataclass
class Moment:
    clip_id: int
    start: float
    end: float
    score: float = 0.0
    sources: set = field(default_factory=set)
    snippet: str = ""
    thumb: str = ""
    best_t: float = 0.0


def tc(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def parse(q: str):
    quoted = re.findall(r"[\"“']([^\"”']+)[\"”']", q)
    rest = re.sub(r"[\"“'][^\"”']+[\"”']", " ", q)
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", rest)
    rest = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", rest)
    return " ".join(rest.split()), quoted, years


def _fts_query(text: str) -> str:
    toks = [t for t in re.findall(r"\w+", text.lower()) if t not in STOP]
    return " ".join(f'"{t}"' for t in toks)


def visual_hits(con, text, k):
    from .embed import embed_text
    vec = embed_text([text])[0]
    rows = con.execute(
        "SELECT v.rowid AS kid, v.distance, k.clip_id, k.t, k.thumb FROM keyframe_vec v "
        "JOIN keyframes k ON k.id = v.rowid WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
        (vec.tobytes(), k)).fetchall()
    # Merge neighbouring keyframes of the same clip into one moment.
    gap = config.KEYFRAME_INTERVAL * 1.6
    by_clip = {}
    for r in rows:
        by_clip.setdefault(r["clip_id"], []).append(r)
    moments = []
    for clip_id, rs in by_clip.items():
        rs.sort(key=lambda r: r["t"])
        cur = None
        for r in rs:
            sim = 1 - r["distance"]
            if cur and r["t"] - cur.end <= gap:
                cur.end = r["t"]
                if sim > cur.score:
                    cur.score, cur.thumb, cur.best_t = sim, r["thumb"], r["t"]
            else:
                cur = Moment(clip_id, r["t"], r["t"], sim, {"visual"}, "", r["thumb"], r["t"])
                moments.append(cur)
    for m in moments:  # pad so a single frame becomes a usable range
        m.start, m.end = max(0, m.start - 1.0), m.end + 1.0
    return sorted(moments, key=lambda m: -m.score)


def speech_hits(con, phrases, limit):
    moments = []
    for ph in phrases:
        q = f'"{ph}"' if " " in ph.strip() else _fts_query(ph)
        if not q:
            continue
        rows = con.execute(
            "SELECT s.id, s.clip_id, s.start, s.end, s.text, bm25(segments_fts) AS rank FROM segments_fts "
            "JOIN segments s ON s.id = segments_fts.rowid WHERE segments_fts MATCH ? ORDER BY rank LIMIT ?",
            (q, limit)).fetchall()
        first = re.findall(r"\w+", ph.lower())
        for r in rows:
            # Snap to the first matching word for an exact in-point.
            words = con.execute("SELECT start, end, word FROM words WHERE segment_id=? ORDER BY start", (r["id"],)).fetchall()
            hit = next((w for w in words if first and first[0] in re.sub(r"\W", "", w["word"].lower())), None)
            start = hit["start"] if hit else r["start"]
            moments.append(Moment(r["clip_id"], max(0, start - 0.3), r["end"], -r["rank"], {"speech"},
                                  r["text"], "", start))
    return moments


def note_hits(con, text, limit):
    toks = [t for t in re.findall(r"\w+", text.lower()) if t not in STOP and len(t) > 2]
    if not toks:
        return []
    need = max(1, (len(toks) + 1) // 2)
    out = []
    for r in con.execute("SELECT m.clip_id, m.start, m.end, m.text FROM moments m"):
        n = sum(t in r["text"].lower() for t in toks)
        if n >= need:
            out.append(Moment(r["clip_id"], r["start"], r["end"], n / len(toks), {"notes"}, r["text"], "", r["start"]))
    tag_rows = con.execute("SELECT clip_id, group_concat(tag, ' ') AS tags, c.caption, c.duration FROM tags "
                           "JOIN clips c ON c.id = clip_id GROUP BY clip_id").fetchall()
    for r in tag_rows:
        blob = f"{r['tags']} {r['caption'] or ''}".lower()
        n = sum(t in blob for t in toks)
        if n >= need:
            out.append(Moment(r["clip_id"], 0, r["duration"], 0.8 * n / len(toks), {"tags"},
                              r["caption"] or r["tags"], "", 0))
    return sorted(out, key=lambda m: -m.score)[:limit]


def _overlaps(a: Moment, b: Moment) -> bool:
    return a.clip_id == b.clip_id and a.start <= b.end + 0.5 and b.start <= a.end + 0.5


def search(con, query, limit=10, mode="hybrid", year=None, tags=()):
    text, quoted, years = parse(query)
    years = [year] if year else years
    lists = []
    content = [t for t in re.findall(r"\w+", text.lower()) if t not in STOP]
    if mode in ("hybrid", "visual") and (content or not quoted):
        lists.append(visual_hits(con, text or query, k=max(limit * 15, 60)))
    if mode in ("hybrid", "speech"):
        lists.append(speech_hits(con, quoted or ([text] if text else []), limit * 3))
    if mode in ("hybrid", "notes") and content:
        lists.append(note_hits(con, text, limit * 3))

    fused: list[Moment] = []
    for lst in lists:
        for rank, m in enumerate(lst):
            rrf = 1 / (60 + rank)
            # Exact speech matches for quoted phrases are what the user asked for: boost.
            if "speech" in m.sources and quoted:
                rrf *= 2
            twin = next((f for f in fused if _overlaps(f, m)), None)
            if twin:
                twin.score += rrf
                twin.sources |= m.sources
                twin.start, twin.end = min(twin.start, m.start), max(twin.end, m.end)
                twin.snippet = twin.snippet or m.snippet
                twin.thumb = twin.thumb or m.thumb
            else:
                fused.append(Moment(m.clip_id, m.start, m.end, rrf, set(m.sources), m.snippet, m.thumb, m.best_t))

    results = []
    for m in sorted(fused, key=lambda m: -m.score):
        c = con.execute("SELECT duration, created_at FROM clips WHERE id=?", (m.clip_id,)).fetchone()
        if years and not any((c["created_at"] or "").startswith(y) for y in years):
            continue
        if tags:
            have = {r["tag"] for r in con.execute("SELECT tag FROM tags WHERE clip_id=?", (m.clip_id,))}
            if not all(any(h == t or h.endswith(":" + t) for h in have) for t in tags):
                continue
        m.end = min(m.end, c["duration"])
        if not m.thumb:
            k = con.execute("SELECT thumb FROM keyframes WHERE clip_id=? ORDER BY abs(t - ?) LIMIT 1",
                            (m.clip_id, m.best_t)).fetchone()
            m.thumb = k["thumb"] if k else ""
        path, online = db.clip_path(con, m.clip_id)
        results.append({
            "file": path, "online": online, "clip_id": m.clip_id,
            "in": round(m.start, 2), "out": round(m.end, 2), "in_tc": tc(m.start), "out_tc": tc(m.end),
            "sources": sorted(m.sources), "score": round(m.score, 4), "snippet": m.snippet, "thumb": m.thumb,
        })
        if len(results) >= limit:
            break
    return results
