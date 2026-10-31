"""Pass 1: Gemini watches a YouTube video window by window and labels every measured change point.

Timing comes from measurement, never from Gemini: cuts.py gives change points (ffmpeg scdet peaks,
low threshold so small overlays are caught), and each one is sent as an exact local still next to the
video window (read straight from the public YouTube URL through Vertex, nothing uploaded). Gemini
labels what changed at each point and adds 'none'-anchored events only for things the meter missed.
Raw responses are saved per window, so a re-run never pays twice.

  python watch.py --id ID --video local.mp4 --cuts ID_cuts3.json --duration 1290 --out <pack>/raw \
                  --transcript ID.json
"""
import argparse, json, os, random, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types
sys.path.insert(0, os.path.dirname(__file__))
from schema import CHUNK

PROMPT = """You are a senior video editor reverse-engineering a YouTuber's editing style so another editor can replicate it exactly.
Watch this window of the video ({a} to {b}, absolute seconds {s:.1f} to {e:.1f}) with its audio.

MEASURED CHANGE POINTS. A frame-difference meter found visual changes at these exact times. Each one has a still
image attached above, labelled with its id, taken just after the change:
{anchors}

Your job:
1. For every change point, decide what editing decision happened there and log it as an event with that anchor_id and
   its exact time as t_start. If one change point carries two decisions (e.g. a cut AND a sound effect), log both.
   If a change point is only body or camera movement, put its id in skipped_anchors instead.
2. Use the still to read on-screen text verbatim, the font look, colours, layout and positions. Use the video to see
   motion (how elements enter and leave, easing, zoom), and the audio for sound effects and music.
3. Only if you clearly see an edit that has no change point near it (slow zooms, small text fading in), log it with
   anchor_id "none" and your best time.
4. t_end is when the element leaves or the shot ends.
5. Times are visual. Never move an event to when the matching words are spoken; the transcript is only for
   spoken_trigger and talk_beat.
6. why = the editorial function, grounded in what is said and shown ("makes the $1 figure concrete as he says it",
   "resets attention after a long talking stretch", "marks list item 2").
{transcript}"""


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    path = os.environ.get("ENV_FILE", os.path.join(os.path.expanduser("~"), ".env"))
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            if line.startswith(name + '='):
                return line.split('=', 1)[1].strip().strip('"')
    sys.exit(f"{name} is not set (environment or {path})")


def mmss(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def transcript_block(words, s, e):
    lines, cur, t0 = [], [], None
    for w in words:
        if w['end'] < s or w['start'] > e:
            continue
        if t0 is None:
            t0 = w['start']
        cur.append(w['text'])
        if w['text'].endswith(('.', '?', '!')) or w['start'] - t0 > 8:
            lines.append(f"[{t0:.1f}] {' '.join(cur)}")
            cur, t0 = [], None
    if cur:
        lines.append(f"[{t0:.1f}] {' '.join(cur)}")
    if not lines:
        return ""
    return "\nWord-timed transcript of this window (absolute seconds):\n" + "\n".join(lines)


def still(video, t, tmp):
    path = os.path.join(tmp, f"{t:.2f}.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                    "-q:v", "4", path], check=True)
    return open(path, "rb").read()


def run_chunk(client, args, words, cuts, s, e):
    path = os.path.join(args.out, f"{args.id}_{int(s):05d}.json")
    if os.path.exists(path):
        return path, "cached"
    mine = [(i, c) for i, c in enumerate(cuts) if s <= c['t'] < e]
    tmp = tempfile.mkdtemp()
    parts, lines = [], []
    for i, c in mine:
        parts.append(types.Part.from_text(text=f"C{i} at {c['t']:.2f}s"))
        parts.append(types.Part.from_bytes(data=still(args.video, c['t'] + args.lag, tmp), mime_type="image/jpeg"))
        lines.append(f"C{i}  t={c['t']:.2f}s  strength={c['score']:.0f}")
    video = types.Part(
        file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={args.id}", mime_type="video/mp4"),
        video_metadata=types.VideoMetadata(start_offset=f"{s:.1f}s", end_offset=f"{e:.1f}s", fps=args.fps))
    prompt = PROMPT.format(a=mmss(s), b=mmss(e), s=s, e=e, anchors="\n".join(lines) or "(none)",
                           transcript=transcript_block(words, s, e))
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=CHUNK,
                                      max_output_tokens=65000, temperature=0.2)
    for attempt in range(8):
        try:
            t = time.time()
            r = client.models.generate_content(model=args.model, contents=[video, *parts, prompt], config=cfg)
            fin = str(r.candidates[0].finish_reason)
            data = json.loads(r.text)
            u = r.usage_metadata
            data["_meta"] = {"id": args.id, "start": s, "end": e, "model": args.model, "fps": args.fps,
                             "anchors": {f"C{i}": c['t'] for i, c in mine},
                             "finish_reason": fin, "secs": round(time.time() - t, 1),
                             "prompt_tokens": u.prompt_token_count, "output_tokens": u.candidates_token_count,
                             "thinking_tokens": u.thoughts_token_count}
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return path, f"{len(mine)} anchors -> {len(data['events'])} events, {fin}, {data['_meta']['secs']}s"
        except Exception as ex:
            msg = str(ex)
            # preview models share a dynamic quota: back off hard, with jitter so parallel windows spread out
            wait = min(300, 45 * 2 ** attempt) * random.uniform(0.7, 1.3) if ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg) else 10
            print(f"  window {int(s)} attempt {attempt + 1} failed: {msg[:160]}; retry in {wait}s", flush=True)
            time.sleep(wait)
    return path, "FAILED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--video", required=True, help="local copy, for exact stills")
    ap.add_argument("--cuts", required=True, help="cuts.py output (threshold 3)")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--transcript")
    ap.add_argument("--window", type=float, default=150)
    ap.add_argument("--overlap", type=float, default=0, help="change points already split windows cleanly")
    ap.add_argument("--lag", type=float, default=0.4, help="seconds after a change point to take its still")
    ap.add_argument("--fps", type=float, default=2)
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--only", type=int, help="run only window N (0-based), for pilots")
    ap.add_argument("--approved-usd", type=float, default=0,
                    help="spend the owner approved in chat for this run; the script refuses if its estimate is higher")
    args = ap.parse_args()
    n_windows = 1 if args.only is not None else int(-(-args.duration // args.window))
    estimate = round(n_windows * 0.31 * args.window / 150, 2)   # measured on the first pack, Gemini 3.1 Pro
    print(f"PAID API: Vertex {args.model}, {n_windows} windows, estimated ${estimate}", flush=True)
    if estimate > args.approved_usd:
        sys.exit(f"Refusing: estimate ${estimate} exceeds --approved-usd {args.approved_usd}. "
                 "Ask the owner first, or use the free path (sheet.py + Claude).")
    os.makedirs(args.out, exist_ok=True)
    words = json.load(open(args.transcript, encoding="utf-8")) if args.transcript else []
    cuts = json.load(open(args.cuts, encoding="utf-8"))
    spans, s = [], 0.0
    while s < args.duration:
        spans.append((max(0.0, s - args.overlap), min(args.duration, s + args.window)))
        s += args.window
    if args.only is not None:
        spans = [spans[args.only]]
    client = genai.Client(vertexai=True, api_key=env("VERTEX_API_KEY"))
    with ThreadPoolExecutor(args.parallel) as pool:
        for path, status in pool.map(lambda sp: run_chunk(client, args, words, cuts, *sp), spans):
            print(os.path.basename(path), status, flush=True)


if __name__ == "__main__":
    main()
