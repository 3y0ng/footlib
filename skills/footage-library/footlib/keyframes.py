"""Scene detection + keyframe extraction into the local thumbnail cache."""
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config


def _secs(tc) -> float:
    return tc.get_seconds() if hasattr(tc, "get_seconds") else float(tc.seconds)


def detect_scenes(path: str, duration: float) -> list[tuple[float, float]]:
    """PySceneDetect content detector; falls back to ffmpeg's scene filter."""
    try:
        from scenedetect import ContentDetector, detect
        scenes = [(_secs(a), _secs(b)) for a, b in detect(path, ContentDetector(), show_progress=False)]
    except Exception:
        scenes = _ffmpeg_scenes(path, duration)
    return scenes or [(0.0, duration)]


def _ffmpeg_scenes(path: str, duration: float, thresh: float = 0.3):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-vf", f"scale=160:-2,select='gt(scene,{thresh})',showinfo",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    cuts = [float(line.split("pts_time:")[1].split()[0]) for line in r.stderr.splitlines() if "pts_time:" in line]
    bounds = [0.0, *cuts, duration]
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]


def plan_keyframes(duration: float, scenes) -> list[tuple[float, str, int]]:
    """Scene midpoints first, then every-N-second frames that aren't too close to one."""
    picks = [((a + b) / 2, "scene", i) for i, (a, b) in enumerate(scenes)]
    t = 0.0
    while t < duration:
        if all(abs(t - p[0]) >= config.KEYFRAME_MIN_GAP for p in picks):
            idx = next((i for i, (a, b) in enumerate(scenes) if a <= t < b), len(scenes) - 1)
            picks.append((t, "interval", idx))
        t += config.KEYFRAME_INTERVAL
    # Never seek past the last decodable frame.
    return sorted((min(t, max(duration - 0.1, 0)), k, i) for t, k, i in picks)


def extract_frame(path: str, t: float, out: Path, width: int = config.THUMB_WIDTH) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out)],
        capture_output=True)
    return r.returncode == 0 and out.exists()


def extract_keyframes(path: str, clip_hash: str, picks) -> list[tuple[float, str, int, str]]:
    folder = config.THUMB_DIR / clip_hash[:2] / clip_hash
    jobs = [(t, k, i, folder / f"{t:09.3f}.jpg") for t, k, i in picks]
    with ThreadPoolExecutor(max_workers=6) as ex:
        ok = list(ex.map(lambda j: j[3].exists() or extract_frame(path, j[0], j[3]), jobs))
    return [(t, k, i, str(p)) for (t, k, i, p), good in zip(jobs, ok) if good]


def contact_sheet(thumbs: list[tuple[float, str]], out: Path, title: str = "", cols: int = 6, max_frames: int = 24):
    """Grid of timestamped thumbnails, for a quick human/VLM look at a clip."""
    from PIL import Image, ImageDraw, ImageFont

    if len(thumbs) > max_frames:
        step = len(thumbs) / max_frames
        thumbs = [thumbs[int(i * step)] for i in range(max_frames)]
    ims = [(t, Image.open(p).convert("RGB")) for t, p in thumbs]
    tw = 256
    th = max(int(im.height * tw / im.width) for _, im in ims)
    rows = (len(ims) + cols - 1) // cols
    head = 28
    sheet = Image.new("RGB", (cols * tw, rows * th + head), "black")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 16)
    except Exception:
        font = ImageFont.load_default()
    d.text((6, 5), title, fill="white", font=font)
    for n, (t, im) in enumerate(ims):
        im = im.resize((tw, int(im.height * tw / im.width)))
        x, y = (n % cols) * tw, head + (n // cols) * th
        sheet.paste(im, (x, y))
        d.rectangle([x, y, x + 62, y + 20], fill="black")
        d.text((x + 4, y + 2), f"{t:5.1f}s", fill="yellow", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out
