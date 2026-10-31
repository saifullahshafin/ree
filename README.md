# REE: Reverse Engineer Edits

**See an editing style you like. Measure exactly how it is built.**

REE is an agent skill (skill name `edit-style-reverse-engineer`, for Claude Code and similar agents) that reverse-engineers a YouTuber's video editing style from their videos into a **style pack**:
a measured log of every edit (when, what, why, how it moves, how it sounds), a style bible where every claim is
a count, rebuild recipes, trigger -> action edit rules, and a visual HTML report.

Inspired by [REA](https://github.com/morluto/rea) ("Reverse Engineer Anything"), which does this for software;
REE does it for video editing. It is an independent project, not part of REA. A repeatable method, not a one-off
analysis. First pack: Ali Abdaal (5 videos, 125 min, 976 measured edits).

## Why it works
Video models describe well but time badly: in testing, model timestamps drifted up to 10 s and followed the
speech instead of the picture. So every time comes from measurement (ffmpeg scene scores, word-timed
transcripts, pixel and audio analysis) and models only label what happens at measured moments.

## Layers
| Layer | Tool | Cost |
|---|---|---|
| Change points | ffmpeg `scdet` + `cuts.py` | free |
| Word timing | Parakeet (`hyperframes transcribe`) | free |
| Labels | Claude on contact sheets (`sheet.py`), or Gemini on Vertex (`watch.py`, asks first) | free / about $0.31 per 150 s |
| Motion specs | 10 fps frame strips, or Gemini (`deep_look.py`, asks first) | free / about $0.07 each |
| Grade and framing | `look.py` (OpenCV, YuNet) | free |
| Sound | Demucs + librosa (`sound.py`, `sfx_events.py`) | free |
| Stats and rules | `merge.py`, `stats.py`, `patterns.py` | free |
| Report | `report.py` -> one HTML page | free |

Paid scripts refuse to run without `--approved-usd` covering their printed estimate.

## Use
Read `SKILL.md` (pipeline), `references/STYLE_BIBLE_RUBRIC.md` (what a style bible must answer) and
`references/GOTCHAS.md` (every failure met so far and its fix).

## Requirements
Python 3.10+, ffmpeg, yt-dlp, Pillow, OpenCV 5, numpy; for sound: torch (CPU), `demucs==4.0.1`, librosa,
soundfile; optional `google-genai` for the paid label pass.

## Publishing rule
Publish the skill and a pack's text and JSON only. Never publish downloaded videos, audio, stills or clips of
the creator's work.
