"""Measured look: colour grade and framing per layout (all numbers from pixels).

For each layout span in the merged events it grabs a still at the span's middle and measures:
- grade: luminance mean, contrast (std), black point (p2), highlight point (p98), saturation, warmth (R/B),
  green-magenta tint ((2G-R-B)/(R+G+B))
- framing (talking-head layouts): largest face's height as % of frame and its centre x/y in %,
  which gives the real punch-in amount (face size close vs medium) and the headroom/side placement

  python look.py --events <pack>/events --sources <pack>/source --out <pack>/look.json
"""
import argparse, glob, json, os, subprocess, tempfile
import statistics as st
from collections import defaultdict
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # OpenCV 5 warns about dnn targets on every detector call
import cv2
import numpy as np

# OpenCV 5 dropped Haar cascades; YuNet (opencv_zoo face_detection_yunet_2023mar.onnx, 232 KB) lives in ../models
YUNET = os.path.join(os.path.dirname(__file__), "..", "models", "face_detection_yunet_2023mar.onnx")
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def frame(video, t):
    p = os.path.join(tempfile.gettempdir(), "look_frame.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", p], check=True)
    return cv2.imread(p)


def grade(img):
    f = img.astype(np.float32) / 255
    b, g, r = f[..., 0].mean(), f[..., 1].mean(), f[..., 2].mean()
    lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return {"r": float(r), "g": float(g), "b": float(b), "luma": float(lum.mean()), "contrast": float(lum.std()), "black_p2": float(np.percentile(lum, 2)),
            "white_p98": float(np.percentile(lum, 98)), "saturation": float(hsv[..., 1].mean() / 255),
            "warmth_r_over_b": float(r / max(b, 1e-3)), "tint": float((2 * g - r - b) / max(r + g + b, 1e-3))}


def face(img):
    if not os.path.exists(YUNET):
        import urllib.request
        os.makedirs(os.path.dirname(YUNET), exist_ok=True)
        urllib.request.urlretrieve(YUNET_URL, YUNET)
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.8)
    _, fs = det.detect(img)
    if fs is None or not len(fs):
        return None
    x, y, fw, fh = max(fs, key=lambda b: b[2] * b[3])[:4]
    return {"face_h_pct": float(100 * fh / h), "face_cx_pct": float(100 * (x + fw / 2) / w),
            "face_cy_pct": float(100 * (y + fh / 2) / h)}


def summary(rows):
    keys = rows[0].keys()
    return {k: {"median": round(st.median(r[k] for r in rows), 3),
                "p25": round(float(np.percentile([r[k] for r in rows], 25)), 3),
                "p75": round(float(np.percentile([r[k] for r in rows], 75)), 3)} for k in keys} | {"n": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-layout", type=int, default=12, help="max stills per layout per video")
    a = ap.parse_args()
    grades, faces = defaultdict(list), defaultdict(list)
    for path in sorted(glob.glob(os.path.join(a.events, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        video = glob.glob(os.path.join(a.sources, d["id"] + "_*.mp4"))[0]
        ev = [e for e in d["events"] if e["anchored"]]
        spans = defaultdict(list)
        for e, nxt in zip(ev, ev[1:] + [None]):
            end = nxt["t_start"] if nxt else e["t_end"]
            if end - e["t_start"] >= 1.5:
                spans[e["layout"]].append((e["t_start"] + end) / 2)
        for layout, mids in spans.items():
            step = max(1, len(mids) // a.per_layout)
            for t in mids[::step][:a.per_layout]:
                img = frame(video, t)
                if img is None:
                    continue
                grades[layout].append(grade(img))
                if layout.startswith("talking_head"):
                    f = face(img)
                    if f:
                        faces[layout].append(f)
        print(d["id"], {k: len(v) for k, v in spans.items()}, flush=True)
    out = {"grade_by_layout": {k: summary(v) for k, v in grades.items()},
           "mean_color_by_layout": {k: "#%02x%02x%02x" % tuple(int(np.median([r[c] for r in v]) * 255)
                                                                for c in ("r", "g", "b")) for k, v in grades.items()},
           "framing_by_layout": {k: summary(v) for k, v in faces.items() if len(v) >= 3}}
    fr = out["framing_by_layout"]
    if "talking_head_medium" in fr:
        base = fr["talking_head_medium"]["face_h_pct"]["median"]
        out["punch_in_scale_vs_medium"] = {k: round(v["face_h_pct"]["median"] / base, 2) for k, v in fr.items()}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps(out.get("punch_in_scale_vs_medium"), indent=1))


if __name__ == "__main__":
    main()
