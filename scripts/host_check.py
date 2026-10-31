"""Measured cross-check of labels: is the frame AFTER each change point the red-lamp studio host shot?

The host set is dark with a red lamp and a red neon strip, so a red-pixel share on the frame at t_start+0.5 s
separates host shots from B-roll well. Compares with the label's layout (talking_head_*) and lists mismatches,
which catches labels that describe the BEFORE frame by mistake.
Usage: python host_check.py <pack> [video_id ...]   -> <pack>/verify/host_check.json
"""
import glob, io, json, os, subprocess, sys
import numpy as np
from PIL import Image


def frame(src, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=96:54",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return np.asarray(Image.open(io.BytesIO(r.stdout)).convert("RGB")).astype(float) if r.stdout else None


def red_share(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return float(((r > 70) & (r > 1.7 * g) & (r > 1.7 * b)).mean())


def main():
    pack, ids = sys.argv[1], sys.argv[2:]
    rows = []
    for lab in sorted(glob.glob(os.path.join(pack, "labels", "*.json"))):
        d = json.load(open(lab, encoding="utf-8"))
        vid = d["_meta"]["id"]
        if ids and vid not in ids:
            continue
        src = glob.glob(os.path.join(pack, "source", vid + "_*.mp4"))[0]
        for e in d["events"]:
            if e.get("anchor_id") in (None, "none"):
                continue
            a = frame(src, e["t_start"] + 0.5)
            if a is None:
                continue
            rows.append({"file": os.path.basename(lab), "anchor": e["anchor_id"], "t": e["t_start"],
                         "layout": e["layout"], "event_type": e["event_type"], "red": round(red_share(a), 4),
                         "luma": round(float(a.mean()), 1)})
    json.dump(rows, open(os.path.join(pack, "verify", "host_check.json"), "w"), indent=0)
    th = [r["red"] for r in rows if r["layout"].startswith("talking_head")]
    ot = [r["red"] for r in rows if not r["layout"].startswith("talking_head")]
    print(f"{len(rows)} events. red share median: host-labelled {np.median(th):.3f} (n={len(th)}), "
          f"other {np.median(ot):.3f} (n={len(ot)})")


if __name__ == "__main__":
    main()
