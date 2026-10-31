"""Pass 2: replication specs for the creator's recurring graphic types.

Pass 1 at 2 fps says WHAT appears. Rebuilding it needs HOW: entrance duration, easing, overshoot,
position, type, stagger. For each graphic_kind this picks the clearest examples (highest confidence,
anchored, spread across videos), re-watches just those seconds at high fps and high media resolution,
and measures the palette from the exact still with k-means (colours are measured, never described).

  python deep_look.py --events <pack>/events --sources <pack>/source --out <pack>/specs --per-kind 3
"""
import argparse, glob, json, os, subprocess, sys, tempfile, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from watch import env

SKIP_KINDS = {"none", "other"}

SPEC = {
    "type": "OBJECT",
    "properties": {
        "element": {"type": "STRING", "description": "what the element is, in one line"},
        "position": {"type": "STRING", "description": "where on the 16:9 frame: anchor and approximate box in % of width/height"},
        "size": {"type": "STRING", "description": "approximate width and height as % of frame"},
        "background_shape": {"type": "STRING", "description": "card, pill, bubble, none... corner radius, border, shadow"},
        "typography": {"type": "STRING", "description": "serif/sans/hand, weight, case, size as % of frame height, line spacing, alignment, highlight style"},
        "entrance": {"type": "STRING", "description": "motion type, direction, duration in ms, easing (linear, ease-out, overshoot spring with % overshoot)"},
        "internal_animation": {"type": "STRING", "description": "what moves after it lands: counters, bars growing, staggered lines with delay in ms, strokes drawing"},
        "exit": {"type": "STRING", "description": "how and how fast it leaves"},
        "camera_and_speaker": {"type": "STRING", "description": "what the speaker footage does meanwhile: PIP size/position/corner radius, zoom, blur, dim"},
        "sound": {"type": "STRING", "description": "sound effects and their sync to motion"},
        "hold_seconds": {"type": "NUMBER"},
        "rebuild_recipe": {"type": "STRING", "description": "step-by-step instructions for an HTML/GSAP or After Effects editor to rebuild this exactly"},
    },
    "required": ["element", "position", "size", "background_shape", "typography", "entrance", "internal_animation",
                 "exit", "camera_and_speaker", "sound", "hold_seconds", "rebuild_recipe"],
}

PROMPT = """You are a motion designer writing a precise rebuild spec. Watch this short excerpt (absolute {s:.1f}s to {e:.1f}s).
Focus on this element, which appears at about {t:.1f}s: {kind}. Earlier notes: "{detail}". On-screen text: "{text}".
Measure, do not guess: count frames for durations (the excerpt is sampled at {fps} fps), estimate positions as % of frame.
If something is not visible, say "not visible"."""


def palette(video, t, k=5):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "f.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", p], check=True)
    im = Image.open(p).convert("RGB").resize((160, 90)).quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal, counts = im.getpalette(), sorted(im.getcolors(), reverse=True)
    return [{"hex": "#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]), "share": round(n / (160 * 90), 3)} for n, i in counts]


def pick(events_dir, per_kind):
    by = defaultdict(list)
    for path in glob.glob(os.path.join(events_dir, "*.json")):
        d = json.load(open(path, encoding="utf-8"))
        for e in d["events"]:
            if e["graphic_kind"] not in SKIP_KINDS and e["anchored"]:
                by[e["graphic_kind"]].append(dict(e, video_id=d["id"]))
    chosen = []
    for kind, evs in by.items():
        evs.sort(key=lambda e: -e["confidence"])
        seen_vid, picks = set(), []
        for e in evs:  # spread across videos first
            if e["video_id"] not in seen_vid:
                picks.append(e); seen_vid.add(e["video_id"])
            if len(picks) == per_kind:
                break
        for e in evs:
            if len(picks) >= per_kind:
                break
            if e not in picks:
                picks.append(e)
        chosen += picks
    return chosen


def look(client, a, e):
    name = f"{e['graphic_kind']}_{e['video_id']}_{e['t_start']:.1f}"
    path = os.path.join(a.out, name + ".json")
    if os.path.exists(path):
        return name, "cached"
    s = max(0.0, e["t_start"] - 1.0)
    end = min(e["t_end"], e["t_start"] + a.max_len) + 1.0 if e["t_end"] > e["t_start"] else e["t_start"] + 6
    video = types.Part(
        file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={e['video_id']}", mime_type="video/mp4"),
        video_metadata=types.VideoMetadata(start_offset=f"{s:.1f}s", end_offset=f"{end:.1f}s", fps=a.fps))
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=SPEC, temperature=0.2,
                                      media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH, max_output_tokens=20000)
    prompt = PROMPT.format(s=s, e=end, t=e["t_start"], kind=e["graphic_kind"], detail=e["visual_detail"],
                           text=e["onscreen_text"][:300], fps=a.fps)
    src = glob.glob(os.path.join(a.sources, e["video_id"] + "_*.mp4"))[0]
    for attempt in range(4):
        try:
            r = client.models.generate_content(model=a.model, contents=[video, prompt], config=cfg)
            spec = json.loads(r.text)
            spec["palette_measured"] = palette(src, e["t_start"] + min(1.5, max(0.4, (e["t_end"] - e["t_start"]) / 2)))
            spec["source_event"] = e
            spec["_usage"] = {"prompt": r.usage_metadata.prompt_token_count, "out": r.usage_metadata.candidates_token_count,
                              "thinking": r.usage_metadata.thoughts_token_count}
            json.dump(spec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return name, "ok"
        except Exception as ex:
            time.sleep(30 * (attempt + 1) if "429" in str(ex) else 10)
            err = str(ex)[:150]
    return name, "FAILED " + err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-kind", type=int, default=3)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--max-len", type=float, default=8)
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--approved-usd", type=float, default=0, help="spend the owner approved in chat for this run")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    client = genai.Client(vertexai=True, api_key=env("VERTEX_API_KEY"))
    todo = pick(a.events, a.per_kind)
    estimate = round(len(todo) * 0.066, 2)   # measured on the first pack: $3.63 for 55 specs
    print(f"PAID API: Vertex {a.model}, {len(todo)} examples, estimated ${estimate}", flush=True)
    if estimate > a.approved_usd:
        sys.exit(f"Refusing: estimate ${estimate} exceeds --approved-usd {a.approved_usd}. Ask the owner first.")
    with ThreadPoolExecutor(a.parallel) as pool:
        for name, status in pool.map(lambda e: look(client, a, e), todo):
            print(name, status, flush=True)


if __name__ == "__main__":
    main()
