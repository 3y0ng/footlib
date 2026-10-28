"""ffprobe metadata: duration, display resolution, fps, codecs, capture date, GPS."""
import json
import re
import subprocess


def _rotation(stream) -> int:
    rot = stream.get("tags", {}).get("rotate")
    if rot is not None:
        return int(rot)
    for sd in stream.get("side_data_list", []):
        if "rotation" in sd:
            return int(sd["rotation"])
    return 0


def _parse_iso6709(s: str):
    # Apple stores e.g. "-33.8688+151.2093+012.000/"
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, check=True,
    ).stdout
    d = json.loads(out)
    fmt = d.get("format", {})
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    vs = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if vs is None:
        raise ValueError("no video stream")
    aus = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)

    w, h = vs.get("width"), vs.get("height")
    if abs(_rotation(vs)) in (90, 270):
        w, h = h, w
    num, den = (vs.get("avg_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else None

    lat, lon = _parse_iso6709(tags.get("com.apple.quicktime.location.iso6709") or tags.get("location"))
    return {
        "duration": float(fmt.get("duration") or vs.get("duration") or 0),
        "width": w, "height": h, "fps": round(fps, 3) if fps else None,
        "vcodec": vs.get("codec_name"),
        "acodec": aus.get("codec_name") if aus else None,
        "has_audio": int(aus is not None),
        "created_at": tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time"),
        "gps_lat": lat, "gps_lon": lon,
        "device": tags.get("com.apple.quicktime.model"),
    }
