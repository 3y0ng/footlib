---
name: footage-library
description: Index a hard drive or folder of video clips into a local searchable library, tag every clip (people, place, shot type, action, mood, quality, project), search by what's on screen or what's said, and get back file + timecode. Also builds organised folder views (by date, project, tag) without moving originals. Use when the user wants to index/scan/catalogue/organise footage, tag clips, find a shot ("me laughing at the whiteboard", anyone saying "pricing"), or pull candidate moments for an edit.
---

# Footage library (footlib)

Local-first: everything runs on this Mac and nothing is uploaded. Originals are only ever **read**, never moved, renamed or modified.

## Running it
Every command below is written as `footlib ...`. Run each one as:

```bash
uv run --quiet --project "<this skill's base directory>" footlib <command> ...
```
Use the folder that contains this SKILL.md, and spell the full prefix out each time. Don't store it in a shell variable: zsh won't split it into words, and shell state doesn't persist between commands anyway.

- **First run:** uv installs Python 3.12 and the dependencies (~2 GB including torch). The first transcribe and embed calls also download the Whisper `small` and SigLIP ViT-B-16 models (~1.3 GB). Tell the user this before starting, and run `footlib doctor` first.
- **Requirements:** ffmpeg (`brew install ffmpeg`) and uv (`brew install uv`). If `doctor` reports something missing, give the user the install command. Don't run installers that need their password.
- **Library location:** `~/.footlib` (DB, thumbnails, contact sheets, overview pages). Set `FOOTLIB_HOME` to put it elsewhere.

## 1. Index a drive or folder
```bash
footlib index "/Volumes/MyDrive"          # ingest + transcribe + embed; incremental and resumable
footlib index ~/Footage --language en     # force transcript language if the footage is all English
footlib status                            # counts, pending work, which drives are online
```
- This can take a long time on big drives (roughly 5–15 s per minute of 4K footage). **Always run it in the background** and report progress from its `[n/N]` lines. Re-running it only processes new or changed files.
- Hashing reads ~3 MB per file (sampled), so big drives aren't read end-to-end just to dedupe. Pass `--full-hash` only if the user wants exact content hashes.
- iCloud "optimised storage" folders download each file on first read. Warn about disk space for those.
- When a drive is unplugged, search still works from cached thumbnails and the results are marked offline.

## 2. Tag clips (you are the vision model)
Tags power search, organisation and the editing workflow. Tag in batches using overview pages:

```bash
footlib pages --untagged [--folder PATH] [--per-page 6]   # writes ~/.footlib/cache/pages/page_NNN.jpg + pages.json
```
1. Read `pages.json` to map page images to `clip_id`s and files.
2. View each page image. Every row is one clip (`#id`, filename, duration), with up to 7 frames stamped with seconds.
3. Write one JSON array per batch following [reference/tagging.md](reference/tagging.md): a caption, tags and timecoded moments for each clip.
4. `footlib annotate batch.json` (this replaces earlier tags from the same source, so it's safe to re-run).
5. For a long clip that needs finer moments, view its own contact sheet (`footlib clips --json` gives `sheet`), or grab a frame with `ffmpeg -ss <t> -i <file> -frames:v 1 -vf scale=640:-2 out.jpg`.

Before tagging a large library (more than ~200 clips), tell the user how many pages it is and agree whether to do all of it or one folder or project first. Use transcripts (`footlib clips --json`) for context, but never put private conversations into captions; tag them `audio:private-conversation` instead.

Hand edits: `footlib tag <clip_id> --add person:sam --remove shot:wide`. User tags are kept separate from auto tags.

## 3. Search
```bash
footlib search "watch on a wrist"                     # visual (SigLIP) + transcript + tags/moments, fused
footlib search "anyone saying 'pricing'"              # quoted text = exact transcript match, snapped to the word
footlib search "blue car at night 2025" --tag project:launch -n 20 --json
```
`--mode visual|speech|notes|hybrid`. A bare year (2025) filters by capture date. `--json` returns `file, in, out, in_tc, out_tc, sources, score, snippet, thumb, online` per moment. Show results as filename + timecode range, and offer to show the thumbnail images.

## 4. Organise (non-destructive)
```bash
footlib organize --by date    --into ~/Footage-by-date      # YYYY/YYYY-MM-DD/
footlib organize --by project --into ~/Footage-by-project   # any tag namespace: project, person, shot, setting...
```
This creates folders of **symlinks** pointing at the originals and moves nothing. Links to an unplugged drive work again once it's plugged back in. Deleting a view folder only deletes the links.

## Other commands
`footlib clips [--untagged] [--folder P] [--json]` lists clips. `footlib ingest`, `footlib transcribe [--model medium]` and `footlib embed` run single stages.
