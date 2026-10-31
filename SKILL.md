---
name: edit-style-reverse-engineer
description: Reverse-engineer a YouTuber's video editing style from their videos into a replicable style pack (measured edit-event dataset, style bible, motion specs, replication recipes). Use when someone wants to copy, study, template or "reverse engineer" how a creator edits (Ali Abdaal style, Hormozi style, MrBeast pacing...), build a creator editing template, or compare editing styles across channels. Not for software reverse engineering (that is REA) and not for editing a new video itself (use the creator's style pack with the editing skills).
---

# Edit Style Reverse Engineer

Turns 3 to 6 of a creator's videos into a **style pack**: every edit they make, when, why, how it moves and
how it sounds, measured and countable, plus recipes another agent can follow to replicate it.

Two layers, never mixed:
- **This skill** = the method (scripts, schema, prompts, verification, synthesis rubric). Creator-neutral.
- **A style pack** = one creator's findings, in its own folder (`<Creator>_Template/`). First pack: Ali Abdaal.

## Money and machines: ask first, guard heavy jobs

- **Free by default.** Measurement, transcription, separation and Claude looking at contact sheets cost nothing
  extra. Any metered API (Gemini on Vertex, OpenRouter, anything billed per token) is OPTIONAL and needs the
  owner's explicit yes in chat for that run, after you state the model, the estimated cost and the free alternative.
  A key in `.env` is not permission. (The first pack spent about $16 of Vertex credit without asking. Never again.)
- **Heavy jobs on a shared VM** run one at a time, under a hard memory cap
  (`systemd-run --user --scope -p MemoryMax=6G ...` or `prlimit --as`), never two in parallel. A VM without swap
  freezes outright when memory runs out; the first pack froze the ARM VM twice this way.

## The core rule: measure first, then let a model describe

Video models describe well but time badly (see `references/GOTCHAS.md`: 10 s errors, anchored to speech
instead of visuals). So every time in a pack comes from measurement, and every claim in a style bible is a
count. A model only labels what happens at measured moments.

| Layer | Tool | Gives |
|---|---|---|
| Change points | ffmpeg `scdet` + `cuts.py` (threshold 3) | exact times of every visual change, including small pop-ups |
| Speech | Parakeet word timings (ARM VM) | exact words, for triggers and talk beats |
| Labels (free default) | the agent reads `label_sheets.py` sheets: before/after frames, motion strip, spectrogram strip per change point | what changed, layout, graphic kind, motion, sound, on-screen text, why |
| Labels (paid option, ask first) | Gemini 3.1 Pro via Vertex, YouTube URL + exact stills per change point (`watch.py`) | the same plus motion and sound heard; about $0.31 per 150 s window |
| Motion specs (free default) | frame strips at 10 fps around an element (`ffmpeg ... -vf fps=10,tile`) read by Claude | durations by frame count, easing, positions |
| Motion specs (paid option, ask first) | Gemini at 10 fps, high media resolution (`deep_look.py`) | the same, written as a spec |
| Colour | k-means on the exact still (`deep_look.py`) | measured hex palette |
| Truth check | contact sheets (`sheet.py`) viewed by Claude | catches mislabels before they become rules |

## One command (UNTESTED as a whole)

`python S/ree_run.py start --pack P --creator "Name" <urls...>` runs steps 1 to 4 (download, change points,
transcription, loudness, sheets) with the slow parts in parallel, then stops for the agent to label.
After `label_sheets.py check` passes, `python S/ree_run.py finish --pack P --creator "Name"` runs merge, stats,
patterns, look, the fast sound pass and the report. Every step it calls is tested; the chain itself has not run
end to end yet. If a step fails, run that step by hand as below.

## Pipeline

Paths below: `S` = this skill's `scripts/`, `P` = the style pack folder. Run Python with `-I` when it reads
downloaded files.

1. **Collect.** 3 to 6 representative long-form videos (different topics, recent, same era of their channel).
   `yt-dlp --ignore-errors --sleep-requests 2 -f "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]" --merge-output-format mp4 --write-info-json -o "%(id)s_%(title).60B.%(ext)s" <urls>`
   into `P/source/`. Do not rely on YouTube captions.
2. **Transcribe** (ARM worker): Opus 16 kHz mono 24 kbps -> scp -> WAV -> `hyperframes transcribe --engine parakeet --json`.
   Word list JSON into `P/data/transcripts/<id>.json`. Check the word count and that the last word ends near the duration.
3. **Measure cuts** (laptop): `ffmpeg -i v.mp4 -an -vf "scdet=threshold=5,metadata=mode=print:file=<id>_scdet.txt" -f null -`,
   then `python S/cuts.py <id>_scdet.txt 10 <id>_cuts.json` (hard cuts) and `... 3 <id>_cuts3.json` (all change points).
4. **Label every change point (free default).** Run sound step 8b first if you can, so sound strips use the
   music+SFX stem instead of the voice-heavy mix. Then
   `python S/label_sheets.py make --id <id> --video <mp4> --cuts <id>_cuts3.json --transcript <t.json> --out P [--audio <no_vocals.wav>]`
   writes one sheet per 60 s window: for each change point a BEFORE | AFTER pair, a 6-frame motion strip
   (-0.3 to +1 s) and a spectrogram strip (-1 to +1 s, red line = the change), plus the transcript and a
   pre-filled label file. The agent reads each sheet and fills `P/labels/<id>_<start>.json` (vocabulary:
   `label_sheets.py vocab`; how: the docstring of label_sheets.py). Times stay as measured.
   About 1.3 s per change point to build; about 1,000 change points per 2 hours of footage.
   Then `python S/label_sheets.py check --labels P/labels` must report 0 problems.
   On the first pack, free labels agreed with the paid pass on 10/11 event types and 10/11 graphic kinds.
5. **(Paid option, only with the owner's yes)** `watch.py` sends the video to Gemini with exact stills per change
   point. It refuses to run unless `--approved-usd` covers its printed estimate. Pilot one window and check it
   on a `sheet.py` contact sheet before scaling.
6. **Merge**: `python S/merge.py --raw P/labels --id <id> --transcript <t.json> --out P/events/<id>.json`
   (use `--raw P/raw_v2` for the paid pass; both use the same schema).
7. **Fingerprint**: `python S/stats.py --events P/events --cuts P/data --out P/fingerprint.json`.
8. **Pass 2 specs**: `python S/deep_look.py --events P/events --sources P/source --out P/specs --per-kind 3`.
8a. **Sound, fast pass (default):** `ffmpeg -i id.m4a -af ebur128 -f null -` for loudness (seconds), then
   `python sound_quick.py --audio full/id.m4a --events events/id.json --out quick/id`: Demucs on 20 random 10 s
   windows (music share, bed level, voice-over-bed gap) and on short windows around edits labelled whoosh, pop
   or typing plus unlabelled controls, each rendered as a 2 s spectrogram with a red line at the edit. The agent
   reads the spectrograms to confirm or reject each sound label. About 5 min per video on 3 ARM cores, instead
   of hours. Run it under the memory cap.
8b. **Sound layer, full (optional, slow)** (ARM, `venv-audio`: torch CPU + `demucs==4.0.1` + librosa): copy the original AAC out of each
   video without re-encoding (`ffmpeg -i v.mp4 -vn -c:a copy id.m4a`), upload, then
   `python sound.py --audio full/id.m4a --words out/id/transcript.json --work sep --out sound/id.json`.
   Gives integrated LUFS, music segments with tempo and ducking depth, timbre change points, and every SFX transient
   with its shape. About 2x slower than real time on 3 ARM cores, so run it detached as soon as the audio is up.
   Then `sfx_join.py` matches SFX to visual events (confirmed / measured only / heard only), and `sfx_name.py`
   lets Gemini listen to one exemplar per SFX cluster and name it.
8c. **Look layer** (laptop): `python S/look.py --events P/events --sources P/source --out P/look.json`:
   grade per layout (luma, contrast, black and white points, saturation, warmth, tint) and framing from YuNet
   face boxes (face size and position, real punch-in scale).
9. **Verify** a stratified sample of the merged events and of the specs on contact sheets. Record the
   accuracy you saw (n checked, n wrong, what kind of wrong) in the pack's README.
10. **Synthesise** the pack (structure below) with `references/STYLE_BIBLE_RUBRIC.md`.

## Style pack layout (what an editing agent reads)

```
<Creator>_Template/
  README.md              how to use this pack, sources, verification results, licence note
  STYLE_BIBLE.md         the style, every claim tagged [measured n/N] or [interpreted]
  RECIPES.md             rebuild recipes per recurring element (from specs/), ready for HyperFrames/GSAP/AE
  EDIT_RULES.md          trigger -> edit rules ("spoken number -> data graphic within 0.5 s, pop + sfx")
  fingerprint.json       measured numbers (stats.py)
  events/<id>.json       full edit-event logs, one per video (the raw material)
  specs/*.json           motion specs with measured palettes
  verify/                contact sheets used to check the labels
  source/, audio/, raw*/ local only, never published (copyrighted footage, re-creatable)
```

## Evidence rules for the style bible
- A rule needs at least 3 occurrences in at least 2 videos. Say how many: "[measured 41/57 events, 5/5 videos]".
- Separate **what** (measured) from **why** (interpreted). Why-claims cite the talk beat and spoken trigger pattern
  that supports them.
- Prefer distributions to single numbers: median and p25 to p75 for shot length, hold time, gaps.
- Note exceptions and where the style shifts (hook vs body, sponsor reads, endings).

## Cost and time (Oct 2026, measured)
About $0.31 and 2 minutes per 150 s window with Gemini 3.1 Pro; two hours of footage is about $15 and
20 to 30 minutes with 3 windows per video in parallel. Transcription is free on the ARM VM (about 5.5x real time).
Claude tokens go to verification sheets and synthesis only, never to watching footage frame by frame.

## Publishing
Publish the skill and the pack's text and JSON. Never publish `source/`, `audio/`, stills or clips of the
creator's videos (see `.gitignore`). Timestamps plus video IDs let anyone re-create the evidence.
