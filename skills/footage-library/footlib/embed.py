"""SigLIP keyframe + text embeddings (open_clip, MPS when available)."""
from functools import lru_cache

import numpy as np

from . import config
from .ingest import now


def device():
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


@lru_cache(maxsize=1)
def load_model():
    import os

    import open_clip
    # Use the local HF cache when the model is already downloaded; go online only the first time.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(config.CLIP_MODEL, pretrained=config.CLIP_PRETRAINED)
        tokenizer = open_clip.get_tokenizer(config.CLIP_MODEL)
    except Exception:
        os.environ["HF_HUB_OFFLINE"] = "0"
        model, _, preprocess = open_clip.create_model_and_transforms(config.CLIP_MODEL, pretrained=config.CLIP_PRETRAINED)
        tokenizer = open_clip.get_tokenizer(config.CLIP_MODEL)
    model = model.to(device()).eval()
    return model, preprocess, tokenizer


def _norm(x: np.ndarray) -> np.ndarray:
    return (x / np.linalg.norm(x, axis=-1, keepdims=True)).astype(np.float32)


def embed_text(texts: list[str]) -> np.ndarray:
    import torch
    model, _, tok = load_model()
    with torch.no_grad():
        return _norm(model.encode_text(tok(texts).to(device())).float().cpu().numpy())


def embed_images(paths: list[str], batch: int = 32) -> np.ndarray:
    import torch
    from PIL import Image
    model, preprocess, _ = load_model()
    out = []
    for i in range(0, len(paths), batch):
        ims = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in paths[i:i + batch]]).to(device())
        with torch.no_grad():
            out.append(model.encode_image(ims).float().cpu().numpy())
    return _norm(np.concatenate(out))


def embed(con, log=print):
    todo = [r["id"] for r in con.execute("SELECT id FROM clips WHERE ingested_at IS NOT NULL AND embedded_at IS NULL")]
    if not todo:
        log("  nothing to embed")
        return 0
    for i, clip_id in enumerate(todo, 1):
        rows = con.execute("SELECT id, thumb FROM keyframes WHERE clip_id=?", (clip_id,)).fetchall()
        if rows:
            vecs = embed_images([r["thumb"] for r in rows])
            con.executemany("DELETE FROM keyframe_vec WHERE rowid=?", [(r["id"],) for r in rows])
            con.executemany("INSERT INTO keyframe_vec(rowid, embedding) VALUES(?,?)",
                            [(r["id"], v.tobytes()) for r, v in zip(rows, vecs)])
        con.execute("UPDATE clips SET embedded_at=? WHERE id=?", (now(), clip_id))
        con.commit()
        log(f"  [{i}/{len(todo)}] ok    clip {clip_id}  {len(rows)} keyframes")
    return len(todo)
