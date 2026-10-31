"""Hindi transcription text through AGY (Gemini via the Antigravity CLI), 2-minute pieces, 3 at a time.

Gemini hears Hindi + English well but its timestamps drift 8-15 s per 2 min (pilot 2026-10-31), so only its
TEXT is used; align_words.py later puts it on the YouTube caption word times.
Usage: python agy_transcribe.py <pack> [video_id ...]
Writes <pack>/data/agy/<id>/<start>.json (Gemini segments, times relative to the piece) and a status log.
Needs a headless Gemini runner with file access: by default the AGY wrapper agy_delegate.py (Antigravity CLI);
point AGY_DELEGATE at your own wrapper with the same --task-file/--workdir interface.
"""
import glob, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

AGY = os.environ.get("AGY_DELEGATE", os.path.expanduser("~/.gemini/tools/claude-bridge/agy_delegate.py"))
PIECE = 120
TASK = """Transcribe the audio file piece.mp3 in your working directory in ONE pass. It is about {n} seconds of spoken Hindi with some English, from a YouTube documentary.

Speed rules (important):
- Open/listen to the whole file ONCE with your file viewing tool. Do NOT split it, do NOT run ffmpeg or any shell command, do NOT create chunk files.
- Do not search the web.

Output rules:
- Hindi words in Devanagari. English words in Latin letters (also common English words said inside Hindi sentences, e.g. knowledge, multiple, questions).
- Segments of about 3 to 8 seconds at natural pauses, start and end seconds from the start of the file, one decimal place.
- Output ONLY a JSON array: [{{"start": 0.0, "end": 4.2, "text": "..."}}, ...]
- Also save it to transcript.json in your working directory.
- If you cannot open the audio, reply exactly CANNOT_OPEN_AUDIO and why. Never invent text.
"""


def piece(pack, vid, src, start, dur):
    out = os.path.join(pack, "data", "agy", vid, f"{start:05d}.json")
    if os.path.exists(out):
        return f"{vid} {start} cached"
    wd = os.path.join(pack, "data", "agy", vid, f"work_{start:05d}")
    os.makedirs(wd, exist_ok=True)
    n = min(PIECE, dur - start)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(n), "-i", src, "-vn", "-ac", "1",
                    "-ar", "16000", "-b:a", "48k", os.path.join(wd, "piece.mp3")], check=True)
    open(os.path.join(wd, "TASK_T.md"), "w", encoding="utf-8").write(TASK.format(n=int(n)))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, AGY, "--task-file", os.path.join(wd, "TASK_T.md"), "--kind", "general",
                        "--workdir", wd, "--timeout", "300", "--retries", "1", "--words", "3000"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    tj = os.path.join(wd, "transcript.json")
    try:
        segs = json.load(open(tj, encoding="utf-8"))
        assert isinstance(segs, list) and segs
    except Exception:
        return f"{vid} {start} FAILED exit={r.returncode} {r.stdout[:120]!r}"
    json.dump(segs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return f"{vid} {start} ok {len(segs)} segs"


def main():
    pack, ids = sys.argv[1], sys.argv[2:]
    jobs = []
    for src in sorted(glob.glob(os.path.join(pack, "source", "*.mp4"))):
        vid = os.path.basename(src)[:11]
        if ids and vid not in ids:
            continue
        info = glob.glob(os.path.join(pack, "source", vid + "_*.info.json"))[0]
        dur = int(json.load(open(info, encoding="utf-8"))["duration"])
        jobs += [(vid, src, s, dur) for s in range(0, dur, PIECE)]
    log = open(os.path.join(pack, "data", "agy_status.log"), "a", encoding="utf-8")
    with ThreadPoolExecutor(3) as pool:
        for msg in pool.map(lambda j: piece(pack, j[0], j[1], j[2], j[3]), jobs):
            print(msg, flush=True)
            log.write(msg + "\n"); log.flush()


if __name__ == "__main__":
    main()
