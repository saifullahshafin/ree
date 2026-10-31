"""Free labelling path (the default): contact sheets for the agent to read, plus pre-filled label files.

The paid path (watch.py) sends video to Gemini. This path costs no API money: the agent running the skill
(e.g. Claude in Claude Code) looks at one sheet per window and fills the labels itself. Output uses the same
schema as watch.py, so merge.py, stats.py and patterns.py work unchanged.

Per window (default 60 s) it writes:
  sheets/<id>_<start>.jpg   every measured change point, numbered C<i> with its time, as: BEFORE | AFTER frames,
                            a 6-frame motion strip (-0.3 to +1 s: how it moves in) and a spectrogram strip
                            (-1 to +1 s, red line = the change: how it sounds). Images are what the agent can read;
                            the strips stand in for watching and listening.
  sheets/<id>_<start>.txt   the word-timed transcript of the window
  labels/<id>_<start>.json  one event stub per change point: anchor_id, t_start, t_end (both measured) and empty
                            fields to fill; enums listed by `label_sheets.py vocab`

  python label_sheets.py make  --id ID --video v.mp4 --cuts ID_cuts3.json --transcript ID.json --out <pack>
  python label_sheets.py vocab                       # the allowed values for every enum field
  python label_sheets.py check --labels <pack>/labels # refuses missing fields and values outside the vocabulary

Agent loop per window: Read the .jpg and .txt, then edit the .json: fill each stub, delete stubs that are not
edits and list their ids in skipped_anchors, duplicate a stub when one change point carries two decisions,
add {"anchor_id": "none"} events only for clear edits with no change point. Set "_meta.labelled": true when done.
Times stay as measured; never move an event to when the words are spoken.
"""
import argparse, glob, json, os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
import schema

ENUMS = {"event_type": schema.EVENT_TYPE, "layout": schema.LAYOUT, "graphic_kind": schema.GRAPHIC_KIND,
         "dimension": schema.DIMENSION, "motion_in": schema.MOTION, "motion_out": schema.MOTION,
         "talk_beat": schema.TALK_BEAT, "speaker_energy": schema.ENERGY, "audio_cue": schema.AUDIO_CUE}
TEXT_FIELDS = ["onscreen_text", "visual_detail", "why"]


def font(size):
    for f in ("arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def grab(video, t, width, tmp):
    p = os.path.join(tmp, f"{t:.2f}.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.2f}", "-i", video, "-frames:v", "1",
                    "-vf", f"scale={width}:-2", "-q:v", "3", p], check=True)
    return Image.open(p).convert("RGB")


def motion_strip(video, t, width, tmp, n=6):
    """n frames from 0.3 s before the change to about 1 s after, side by side: shows how things move in."""
    p = os.path.join(tmp, f"m{t:.2f}.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t - 0.3):.2f}", "-i", video, "-t", "1.3",
                    "-vf", f"fps={n / 1.3:.3f},scale={width // n}:-2,tile={n}x1", "-frames:v", "1", p], check=True)
    return Image.open(p).convert("RGB")


def sound_strip(audio, t, width, height, tmp):
    """Spectrogram from 1 s before to 1 s after the change, red line at the change: whoosh = broad swell,
    pop = sharp vertical line, music = steady horizontal bands. Use the music+SFX stem when there is one."""
    p = os.path.join(tmp, f"s{t:.2f}.png")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t - 1):.2f}", "-t", "2", "-i", audio,
                        "-lavfi", f"showspectrumpic=s={width}x{height}:legend=0:scale=log:fscale=log:color=intensity", p])
    if r.returncode or not os.path.exists(p):
        return None
    im = Image.open(p).convert("RGB")
    ImageDraw.Draw(im).line([(im.width // 2, 0), (im.width // 2, im.height)], fill=(255, 40, 40), width=1)
    return im


def words_text(words, s, e):
    lines, cur, t0 = [], [], None
    for w in words:
        if w["end"] < s or w["start"] > e:
            continue
        t0 = w["start"] if t0 is None else t0
        cur.append(w["text"])
        if w["text"].endswith((".", "?", "!")) or w["start"] - t0 > 8:
            lines.append(f"[{t0:.1f}] {' '.join(cur)}"); cur, t0 = [], None
    if cur:
        lines.append(f"[{t0:.1f}] {' '.join(cur)}")
    return "\n".join(lines)


def make(a):
    cuts = json.load(open(a.cuts, encoding="utf-8"))
    words = json.load(open(a.transcript, encoding="utf-8")) if a.transcript else []
    dur = a.duration or float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                              "csv=p=0", a.video], capture_output=True, text=True).stdout)
    sd, ld = os.path.join(a.out, "sheets"), os.path.join(a.out, "labels")
    os.makedirs(sd, exist_ok=True); os.makedirs(ld, exist_ok=True)
    tmp, f_lab, s = tempfile.mkdtemp(), font(max(14, a.tile // 24)), 0.0
    while s < dur:
        e = min(dur, s + a.window)
        name = f"{a.id}_{int(s):05d}"
        mine = [(i, c["t"]) for i, c in enumerate(cuts) if s <= c["t"] < e]
        if not os.path.exists(os.path.join(ld, name + ".json")):
            tiles = []
            for i, t in mine:
                pair = [grab(a.video, t - a.before, a.tile, tmp), grab(a.video, t + a.lag, a.tile, tmp)]
                w, h = pair[0].size
                W = 2 * w + 6
                strips = []
                if not a.no_motion:
                    strips.append(motion_strip(a.video, t, W, tmp))
                if not a.no_sound:
                    sp = sound_strip(a.audio or a.video, t, W, max(60, h // 3), tmp)
                    if sp:
                        strips.append(sp)
                im = Image.new("RGB", (W, h + 26 + sum(x.height + 4 for x in strips)), (20, 20, 20))
                im.paste(pair[0], (0, 26)); im.paste(pair[1], (w + 6, 26))
                y = h + 30
                for x in strips:
                    im.paste(x, (0, y)); y += x.height + 4
                d = ImageDraw.Draw(im)
                d.text((6, 4), f"C{i}  {int(t // 60):02d}:{t % 60:05.2f}   before | after   (motion -0.3..+1 s, sound -1..+1 s)",
                       fill=(255, 220, 0), font=f_lab)
                tiles.append(im)
            if tiles:
                tw, th = tiles[0].size
                rows = (len(tiles) + a.cols - 1) // a.cols
                sheet = Image.new("RGB", (a.cols * tw + (a.cols - 1) * 8, rows * th + (rows - 1) * 8), (40, 40, 40))
                for k, im in enumerate(tiles):
                    sheet.paste(im, ((k % a.cols) * (tw + 8), (k // a.cols) * (th + 8)))
                sheet.save(os.path.join(sd, name + ".jpg"), quality=85)
            open(os.path.join(sd, name + ".txt"), "w", encoding="utf-8").write(words_text(words, s, e))
            times = [t for _, t in mine] + [e]
            stubs = [{"anchor_id": f"C{i}", "t_start": round(t, 2), "t_end": round(times[k + 1], 2),
                      **{f: "" for f in ENUMS}, **{f: "" for f in TEXT_FIELDS},
                      "spoken_trigger": "", "confidence": None} for k, (i, t) in enumerate(mine)]
            json.dump({"_meta": {"id": a.id, "start": s, "end": e, "labeller": "agent-contact-sheet",
                                 "finish_reason": "MANUAL", "labelled": False,
                                 "anchors": {f"C{i}": t for i, t in mine}},
                       "segment_summary": "", "music_present": None, "music_character": "", "dominant_layout": "",
                       "events": stubs, "skipped_anchors": []},
                      open(os.path.join(ld, name + ".json"), "w", encoding="utf-8"), indent=1)
        print(name, len(mine), "change points", flush=True)
        s += a.window


def check(a):
    bad, todo, n = [], [], 0
    for p in sorted(glob.glob(os.path.join(a.labels, "*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        name = os.path.basename(p)
        if not d["_meta"].get("labelled"):
            todo.append(name); continue
        if d["dominant_layout"] not in schema.LAYOUT:
            bad.append(f"{name}: dominant_layout '{d['dominant_layout']}'")
        anchors = d["_meta"]["anchors"]
        covered = {e["anchor_id"] for e in d["events"]} | set(d["skipped_anchors"])
        for aid in anchors:
            if aid not in covered:
                bad.append(f"{name}: {aid} neither labelled nor skipped")
        for e in d["events"]:
            n += 1
            for f, allowed in ENUMS.items():
                if e.get(f) not in allowed:
                    bad.append(f"{name} {e.get('anchor_id')}: {f}='{e.get(f)}'")
            if not e.get("why"):
                bad.append(f"{name} {e.get('anchor_id')}: why is empty")
            if e["anchor_id"] in anchors and abs(e["t_start"] - anchors[e["anchor_id"]]) > 0.05:
                bad.append(f"{name} {e['anchor_id']}: t_start moved off the measured time")
            if not isinstance(e.get("confidence"), (int, float)):
                bad.append(f"{name} {e.get('anchor_id')}: confidence missing")
    print(f"{n} events checked, {len(todo)} windows not labelled yet, {len(bad)} problems")
    for b in bad[:40]:
        print("  ", b)
    sys.exit(1 if bad or todo else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--id", required=True); m.add_argument("--video", required=True)
    m.add_argument("--cuts", required=True); m.add_argument("--transcript")
    m.add_argument("--out", required=True); m.add_argument("--duration", type=float)
    m.add_argument("--window", type=float, default=60); m.add_argument("--tile", type=int, default=400)
    m.add_argument("--cols", type=int, default=2)
    m.add_argument("--before", type=float, default=0.3, help="seconds before the change point")
    m.add_argument("--lag", type=float, default=0.4, help="seconds after the change point")
    m.add_argument("--audio", help="music+SFX stem (sound.py's no_vocals.wav) for clearer sound strips; default: the video")
    m.add_argument("--no-motion", action="store_true"); m.add_argument("--no-sound", action="store_true")
    c = sub.add_parser("check"); c.add_argument("--labels", required=True)
    sub.add_parser("vocab")
    a = ap.parse_args()
    if a.cmd == "make":
        make(a)
    elif a.cmd == "check":
        check(a)
    else:
        print(json.dumps(ENUMS, indent=1))
