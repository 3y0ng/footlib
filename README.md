# footlib

Apple Photos for video footage, run from Claude Code. Point it at a hard drive or folder full of clips, and Claude:

- **indexes** every clip: dedupe, metadata (date, resolution, fps, GPS), scene-detected keyframes, thumbnails, transcripts with word timestamps, and SigLIP visual embeddings
- **tags** every clip by looking at its frames: a caption, people, place, shot type, action, mood, quality, project, and timecoded moments
- **searches** by what's on screen *or* what's said ("me laughing at the whiteboard", anyone saying "pricing") and returns **file + in/out timecode**
- **organises** the library into folder views by date, project or any tag, using symlinks, so originals are never moved

Everything runs locally on Apple Silicon (MPS). Nothing is uploaded, and your original files are only ever read.

## Install

You need [uv](https://docs.astral.sh/uv/) and ffmpeg:

```bash
brew install uv ffmpeg
```

Then in Claude Code:

```
/plugin marketplace add 3y0ng/footlib
/plugin install footlib@footlib
```

Or, without the plugin system:

```bash
git clone https://github.com/3y0ng/footlib ~/.claude/footlib
ln -s ~/.claude/footlib/skills/footage-library ~/.claude/skills/footage-library
```

The first run installs Python dependencies (~2 GB, including torch) and downloads the Whisper and SigLIP models (~1.3 GB).

## Use

Just ask Claude:

- "Index my footage drive at /Volumes/T7"
- "Tag everything that's untagged"
- "Find clips of me walking the dog at night"
- "Anyone saying 'launch date'?"
- "Organise my footage by project into ~/Footage-by-project"

Or run the CLI directly (from `skills/footage-library`):

```bash
uv run footlib doctor
uv run footlib index /Volumes/T7
uv run footlib search "close-up of hands opening a box" --json
uv run footlib pages --untagged        # overview pages for tagging
uv run footlib annotate batch.json     # import tags
uv run footlib organize --by date --into ~/Footage-by-date
```

The library lives in `~/.footlib` (override with `FOOTLIB_HOME`). It keeps working when the drive is unplugged: thumbnails stay cached, and results are marked offline until you plug the drive back in.

## How it works

| Stage | Tooling |
|---|---|
| Ingest | sampled sha256 (size + 3 × 1 MB), ffprobe, PySceneDetect, ffmpeg keyframes every 2 s + scene midpoints |
| Transcribe | faster-whisper `small` (CPU int8), word timestamps, VAD, language-confidence filter |
| Embed | open_clip SigLIP ViT-B-16 on MPS → sqlite-vec |
| Tag | Claude reads overview pages and writes captions/tags/moments (`reference/tagging.md`) |
| Search | SigLIP KNN + SQLite FTS5 + tag/moment match, fused with reciprocal rank fusion |
| Store | SQLite + sqlite-vec, local thumbnail cache |
