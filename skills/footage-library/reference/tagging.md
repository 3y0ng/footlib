# Tagging format

`footlib annotate batch.json` takes an array, one object per clip:

```json
[
  {
    "clip_id": 42,
    "caption": "Top-down unboxing of a fitness tracker on a wave-print desk mat, watch lying beside it",
    "tags": ["shot:top-down", "action:unboxing", "subject:fitness-tracker", "setting:desk",
             "sound:asmr", "quality:good", "project:fitbit-air"],
    "moments": [
      {"start": 0.0, "end": 4.0, "text": "box set down next to the watch"},
      {"start": 28.0, "end": 40.0, "text": "inner box opened, woven band revealed"}
    ]
  }
]
```

`file` (a path or bare filename) can be used instead of `clip_id`. `source` defaults to `vlm`; user edits use `user`.

## Tag namespaces
Use lowercase, with hyphens inside values. Reuse existing values where they fit (check with `footlib clips`).

| Namespace | Examples |
|---|---|
| `shot:` | talking-head, b-roll, screen-recording, wide, medium, close, macro, top-down, pov, orbit, push-in, product |
| `subject:` | the main objects: car, watch, dog, laptop, product name |
| `person:` | names once the user tells you who someone is; otherwise `person:unknown-1` |
| `action:` | unboxing, walking, driving, cooking, talking, typing |
| `setting:` | desk, kitchen, street, car, store, gym, beach, office |
| `place:` | named places or stores if visible or known: jb-hi-fi, bondi |
| `mood:` | calm, energetic, funny, moody, golden-hour, night |
| `quality:` | good, blurry, shaky, dark, overexposed, bad-audio, unusable |
| `audio:` | speech, music, asmr, silent, private-conversation |
| `beat:` | edit roles: hook, setup, payoff, cta, transition |
| `project:` | groups clips for an edit or shoot |
| `story:` | facts the user tells you about the narrative: sold-out, bought |

## Moments
- Describe what happens, not the camera settings: "hand lifts lid, band revealed".
- Timecodes come from the stamps on the frames. Keep moments 1–15 s long and make them tight enough to drop straight into an edit.
- Long clips (over 60 s) should get 3–8 moments. Short clips can have one, or none if the caption covers it.
- Flag sensitive content in tags (for example, an account email visible on screen) instead of describing it.
