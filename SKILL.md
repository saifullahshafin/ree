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
| Labels (free default) | Claude views contact sheets of the stills at each change point (`sheet.py`), in batches | what changed, layout, graphic kind, on-screen text, why |
| Labels (paid option, ask first) | Gemini 3.1 Pro via Vertex, YouTube URL + exact stills per change point (`watch.py`) | the same plus motion and sound heard; about $0.31 per 150 s window |
| Motion specs (free default) | frame strips at 10 fps around an element (`ffmpeg ... -vf fps=10,tile`) read by Claude | durations by frame count, easing, positions |
| Motion specs (paid option, ask first) | Gemini at 10 fps, high media resolution (`deep_look.py`) | the same, written as a spec |
| Colour | k-means on the exact still (`deep_look.py`) | measured hex palette |
| Truth check | contact sheets (`sheet.py`) viewed by Claude | catches mislabels before they become rules |

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
4. **Pilot.** `python S/watch.py --id <id> --video <mp4> --cuts <id>_cuts3.json --duration <s> --out P/raw_v2 --transcript <t.json> --only 1`.
   Then `python S/sheet.py <mp4> P/verify/pilot.jpg --events P/raw_v2/<id>_00150.json --sample 12 --offset 0.4`
   and LOOK at the sheet against the printed labels. Fix the prompt before scaling. Never skip this.
5. **Pass 1, all videos**, same command without `--only` (3 parallel windows per video).
6. **Merge**: `python S/merge.py --raw P/raw_v2 --id <id> --transcript <t.json> --out P/events/<id>.json`.
7. **Fingerprint**: `python S/stats.py --events P/events --cuts P/data --out P/fingerprint.json`.
8. **Pass 2 specs**: `python S/deep_look.py --events P/events --sources P/source --out P/specs --per-kind 3`.
8b. **Sound layer** (ARM, `venv-audio`: torch CPU + `demucs==4.0.1` + librosa): copy the original AAC out of each
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
