"""faster-whisper transcripts with word timestamps (CPU int8; CTranslate2 has no MPS)."""
import os
import subprocess
import sys

import numpy as np

from . import config, db
from .ingest import now


def load_audio(path: str, sr: int = 16000) -> np.ndarray:
    """Decode to 16 kHz mono float32 with ffmpeg (avoids faster-whisper's PyAV version coupling)."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def transcribe(con, model_name=None, force=False, log=print, language=None):
    from faster_whisper import WhisperModel

    q = "SELECT id FROM clips WHERE has_audio=1" + ("" if force else " AND transcribed_at IS NULL")
    todo = [r["id"] for r in con.execute(q)]
    if not todo:
        log("  nothing to transcribe")
        return 0
    model = WhisperModel(model_name or config.WHISPER_MODEL, device="cpu", compute_type="int8",
                         cpu_threads=os.cpu_count() or 4)
    n = 0
    for i, clip_id in enumerate(todo, 1):
        path, online = db.clip_path(con, clip_id)
        if not online:
            log(f"  offline, skipped clip {clip_id}: {path}")
            continue
        try:
            segs, info = model.transcribe(load_audio(path), word_timestamps=True, vad_filter=True, beam_size=5,
                                          condition_on_previous_text=False, language=language)
            segs = list(segs)
            if not language and info.language_probability < 0.6:
                segs = []  # no clear speech: Whisper tends to hallucinate here
        except Exception as e:
            print(f"  ERROR {path}: {e}", file=sys.stderr)
            continue
        old = [r["id"] for r in con.execute("SELECT id FROM segments WHERE clip_id=?", (clip_id,))]
        for sid in old:
            con.execute("INSERT INTO segments_fts(segments_fts, rowid, text) "
                        "SELECT 'delete', id, text FROM segments WHERE id=?", (sid,))
        con.execute("DELETE FROM words WHERE clip_id=?", (clip_id,))
        con.execute("DELETE FROM segments WHERE clip_id=?", (clip_id,))
        kept = 0
        for s in segs:
            # Drop the usual Whisper hallucinations on music/silence.
            if s.no_speech_prob > 0.6 and s.avg_logprob < -0.8:
                continue
            text = s.text.strip()
            if not text:
                continue
            sid = con.execute("INSERT INTO segments(clip_id,start,end,text,language) VALUES(?,?,?,?,?)",
                              (clip_id, s.start, s.end, text, info.language)).lastrowid
            con.execute("INSERT INTO segments_fts(rowid, text) VALUES(?,?)", (sid, text))
            con.executemany("INSERT INTO words VALUES(?,?,?,?,?,?)",
                            [(sid, clip_id, w.start, w.end, w.word.strip(), w.probability) for w in s.words or []])
            kept += 1
        con.execute("UPDATE clips SET transcribed_at=? WHERE id=?", (now(), clip_id))
        con.commit()
        n += 1
        log(f"  [{i}/{len(todo)}] ok    {os.path.basename(path)}  {kept} segments")
    return n
