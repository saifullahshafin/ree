"""ree run: one command for the measured part of a style pack (UNTESTED as a whole; every step it calls is tested).

  python ree_run.py start  --pack <dir> --creator "Name" <youtube urls...> [--remote HOST] [--remote-dir DIR]
  (the agent labels <pack>/labels with the sheets, then `label_sheets.py check` must pass)
  python ree_run.py finish --pack <dir> --creator "Name"

start:  download 480p (laptop) -> in parallel: change points (laptop ffmpeg), transcription (remote Parakeet),
        loudness (laptop ebur128) -> sheets + label stubs (laptop) -> prints the labelling hand-over.
        Sheets use the full mix for sound strips; the fast sound pass runs in `finish` once labels exist.
finish: merge -> stats -> patterns -> look -> fast sound pass on the remote (sampled Demucs, memory-capped,
        one video at a time) -> report.html.
Free: no paid API is called. Remote work stays in --remote-dir. Nothing is published.
"""
import argparse, glob, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def sh(cmd, **kw):
    print("  $", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True)
    return subprocess.run(cmd, check=True, **kw)


def ssh(host, cmd):
    return sh(["ssh", "-n", "-o", "BatchMode=yes", host, cmd], capture_output=True, text=True)


def vid_ids(pack):
    return sorted(os.path.basename(p)[:11] for p in glob.glob(os.path.join(pack, "source", "*.mp4")))


def video(pack, vid):
    return glob.glob(os.path.join(pack, "source", vid + "_*.mp4"))[0]


def changes(pack, vid):
    d = os.path.join(pack, "data")
    sc = os.path.join(d, f"{vid}_scdet.txt")
    if not os.path.exists(sc):
        sh(["ffmpeg", "-v", "error", "-nostats", "-i", video(pack, vid), "-an", "-vf",
            f"scdet=threshold=5,metadata=mode=print:file={sc.replace(os.sep, '/').replace(':', chr(92) + ':')}",
            "-f", "null", "-"])
    for th, suffix in ((10, "_cuts.json"), (3, "_cuts3.json")):
        sh([PY, os.path.join(HERE, "cuts.py"), sc, str(th), os.path.join(d, vid + suffix)])


def transcribe(pack, vid, host, rdir):
    out = os.path.join(pack, "data", "transcripts", vid + ".json")
    if os.path.exists(out):
        return
    au = os.path.join(pack, "audio", vid + ".opus")
    sh(["ffmpeg", "-v", "error", "-y", "-i", video(pack, vid), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus",
        "-b:a", "24k", au])
    sh(["scp", "-q", au, f"{host}:{rdir}/media/"])
    ssh(host, f"cd {rdir} && source ../../env.sh && ffmpeg -v error -y -i media/{vid}.opus -ar 16000 -ac 1 media/{vid}.wav"
              f" && npx -y hyperframes@0.8.169 transcribe media/{vid}.wav --engine parakeet --json -d out/{vid} > /dev/null")
    sh(["scp", "-q", f"{host}:{rdir}/out/{vid}/transcript.json", out])


def loudness(pack, vid):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video(pack, vid), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    get = lambda k: next((float(l.split()[1]) for l in tail.splitlines() if l.strip().startswith(k)), None)
    return {"lufs": get("I:"), "lra": get("LRA:")}


def start(a):
    p = a.pack
    for sub in ("source", "audio", "audio_full", "data/transcripts", "sound/mix", "sound/quick", "verify"):
        os.makedirs(os.path.join(p, sub), exist_ok=True)
    sh(["yt-dlp", "--ignore-errors", "--sleep-requests", "2", "-f", "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480]",
        "--merge-output-format", "mp4", "--write-info-json", "-o", os.path.join(p, "source", "%(id)s_%(title).60B.%(ext)s"), *a.urls])
    ids = vid_ids(p)
    ssh(a.remote, f"mkdir -p {a.remote_dir}/media {a.remote_dir}/out {a.remote_dir}/full {a.remote_dir}/events")
    with ThreadPoolExecutor(3) as pool:   # CPU work on the laptop overlaps network/remote work
        jobs = [pool.submit(changes, p, v) for v in ids] + [pool.submit(transcribe, p, v, a.remote, a.remote_dir) for v in ids]
        for j in jobs:
            j.result()
    json.dump({v: loudness(p, v) for v in ids}, open(os.path.join(p, "sound", "loudness.json"), "w"), indent=1)
    for v in ids:
        sh([PY, os.path.join(HERE, "label_sheets.py"), "make", "--id", v, "--video", video(p, v),
            "--cuts", os.path.join(p, "data", v + "_cuts3.json"), "--transcript", os.path.join(p, "data", "transcripts", v + ".json"),
            "--out", p])
    n = len(glob.glob(os.path.join(p, "labels", "*.json")))
    print(f"\nREADY TO LABEL: {n} windows in {p}/labels (sheets in {p}/sheets). Split by video across agents if you like.\n"
          f"Then: python {HERE}/label_sheets.py check --labels {p}/labels  and  python ree_run.py finish ...")


def finish(a):
    p = a.pack
    r = subprocess.run([PY, os.path.join(HERE, "label_sheets.py"), "check", "--labels", os.path.join(p, "labels")])
    if r.returncode:
        sys.exit("Labels are incomplete or invalid; fix them first (label_sheets.py check).")
    ids = vid_ids(p)
    for v in ids:
        sh([PY, os.path.join(HERE, "merge.py"), "--raw", os.path.join(p, "labels"), "--id", v,
            "--transcript", os.path.join(p, "data", "transcripts", v + ".json"), "--out", os.path.join(p, "events", v + ".json")])
    sh([PY, os.path.join(HERE, "stats.py"), "--events", os.path.join(p, "events"), "--cuts", os.path.join(p, "data"),
        "--transcripts", os.path.join(p, "data", "transcripts"), "--out", os.path.join(p, "fingerprint.json")])
    sh([PY, os.path.join(HERE, "patterns.py"), "--events", os.path.join(p, "events"), "--transcripts",
        os.path.join(p, "data", "transcripts"), "--out", os.path.join(p, "patterns.json")])
    sh([PY, os.path.join(HERE, "look.py"), "--events", os.path.join(p, "events"), "--sources", os.path.join(p, "source"),
        "--out", os.path.join(p, "look.json")])
    if not a.skip_sound:
        R, rd = a.remote, a.remote_dir
        sh(["scp", "-q", os.path.join(HERE, "sound_quick.py"), f"{R}:{rd}/"])
        for v in ids:
            m4a = os.path.join(p, "audio_full", v + ".m4a")
            if not os.path.exists(m4a):
                sh(["ffmpeg", "-v", "error", "-y", "-i", video(p, v), "-vn", "-c:a", "copy", m4a])
            sh(["scp", "-q", m4a, f"{R}:{rd}/full/"])
            sh(["scp", "-q", os.path.join(p, "events", v + ".json"), f"{R}:{rd}/events/"])
            ssh(R, f"cd {rd} && sudo -n systemd-run --quiet --scope -p MemoryMax=6G -p MemorySwapMax=0 --uid=$(id -u) --gid=$(id -g) "
                   f"nice -n 10 {a.remote_python} sound_quick.py --audio full/{v}.m4a --events events/{v}.json --out quick/{v}")
            os.makedirs(os.path.join(p, "sound", "quick", v), exist_ok=True)
            sh(["scp", "-q", "-r", f"{R}:{rd}/quick/{v}/*", os.path.join(p, "sound", "quick", v)])
        print("Sound spectrograms are in sound/quick/<id>/: read them before writing any sound rule.")
    sh([PY, os.path.join(HERE, "report.py"), "--pack", p, "--creator", a.creator, "--out", os.path.join(p, "report.html")])
    print(f"\nDONE: {p}/report.html. Next: write STYLE_BIBLE.md, EDIT_RULES.md, RECIPES.md with references/STYLE_BIBLE_RUBRIC.md.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "finish"):
        s = sub.add_parser(name)
        s.add_argument("--pack", required=True); s.add_argument("--creator", required=True)
        s.add_argument("--remote", default=os.environ.get("REE_REMOTE", "Hunter-A1-Flex"))
        s.add_argument("--remote-dir", default=os.environ.get("REE_REMOTE_DIR", "/mnt/data/video-studio/jobs/ree"))
        s.add_argument("--remote-python", default=os.environ.get("REE_REMOTE_PY", "/mnt/data/video-studio/venv-audio/bin/python"))
        if name == "start":
            s.add_argument("urls", nargs="+")
        else:
            s.add_argument("--skip-sound", action="store_true")
    a = ap.parse_args()
    start(a) if a.cmd == "start" else finish(a)
