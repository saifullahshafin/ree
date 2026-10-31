"""In-shot motion pass: what moves INSIDE each shot, measured on every sampled frame (default 10 fps).

The change-point pipeline only sees the moments where the picture changes. This pass fills the gap:
- head motion of the main face (YuNet landmarks): roll = head tilt in degrees from the eye line, yaw and pitch
  proxies from the nose position; swings counted per second, with and without speech
- camera motion between frames of the same shot (LK optical flow + similarity fit): zoom %/s, pan/tilt in % of
  frame width per second, roll, and shake (frame-to-frame jitter)
- mid-shot pop-ins: localised changes inside a shot with no change point (text, icons, overlays appearing)
- brightness per frame (fades, flashes)
Free and local (OpenCV + ffmpeg). About 5-10 min per 25 min of 480p video on a laptop CPU.

  python inshot_motion.py --video v.mp4 --cuts ID_cuts3.json --out P/motion/ID.json
         [--transcript ID.json] [--events P/events/ID.json] [--fps 10]
"""
import argparse, bisect, json, os, subprocess, sys, urllib.request
import numpy as np
import cv2

YUNET = os.path.join(os.path.dirname(__file__), "..", "models", "face_detection_yunet_2023mar.onnx")
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
W = 640


def frames(video, fps):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", video], capture_output=True, text=True).stdout.strip().split(",")
    h = int(round(int(p[1]) * W / int(p[0]) / 2) * 2)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={fps},scale={W}:{h}", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    n = W * h * 3
    while True:
        buf = proc.stdout.read(n)
        if len(buf) < n:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, W, 3)


def face(det, img):
    _, f = det.detect(img)
    if f is None or not len(f):
        return None
    big = max(r[2] * r[3] for r in f)
    n = sum(r[2] * r[3] > 0.5 * big for r in f)
    f = max(f, key=lambda r: r[2] * r[3])
    x, y, w, h = f[:4]
    re_, le, no = f[4:6], f[6:8], f[8:10]
    mid = (re_ + le) / 2
    eye = np.linalg.norm(le - re_) + 1e-6
    roll = float(np.degrees(np.arctan2(le[1] - re_[1], le[0] - re_[0])))
    return {"roll": roll, "yaw": float((no[0] - mid[0]) / eye), "pitch": float((no[1] - mid[1]) / eye),
            "size": float(h / img.shape[0]), "w": float(w / img.shape[1]), "n": int(n),
            "cx": float((x + w / 2) / img.shape[1]), "cy": float((y + h / 2) / img.shape[0])}


def camera(prev, cur):
    pts = cv2.goodFeaturesToTrack(prev, 200, 0.01, 8)
    if pts is None or len(pts) < 12:
        return None
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None)
    a, b = pts[st == 1], nxt[st == 1]
    if len(a) < 12:
        return None
    m, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=1.5)
    if m is None or inl.sum() < 12:
        return None
    s = float(np.hypot(m[0, 0], m[1, 0]))
    return {"scale": s, "rot": float(np.degrees(np.arctan2(m[1, 0], m[0, 0]))),
            "tx": float(m[0, 2] / prev.shape[1]), "ty": float(m[1, 2] / prev.shape[1]), "inliers": int(inl.sum())}


def swings(xs, thr):
    """Zigzag: amplitudes of completed swings between turning points that differ by at least thr."""
    out = []
    if not xs:
        return out
    piv = ext = xs[0]
    d = 0
    for x in xs[1:]:
        if d == 0:
            if abs(x - piv) >= thr:
                d, ext = (1 if x > piv else -1), x
        elif d == 1:
            if x > ext:
                ext = x
            elif ext - x >= thr:
                out.append(ext - piv); piv, ext, d = ext, x, -1
        else:
            if x < ext:
                ext = x
            elif x - ext >= thr:
                out.append(piv - ext); piv, ext, d = ext, x, 1
    return out


def med(v):
    return round(float(np.median(v)), 3) if len(v) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--cuts", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--transcript"); ap.add_argument("--events"); ap.add_argument("--fps", type=float, default=10)
    a = ap.parse_args()
    if not os.path.exists(YUNET):
        os.makedirs(os.path.dirname(YUNET), exist_ok=True)
        urllib.request.urlretrieve(YUNET_URL, YUNET)
    cuts = sorted(c["t"] for c in json.load(open(a.cuts)))
    words = json.load(open(a.transcript, encoding="utf-8")) if a.transcript else []
    wst = [w["start"] for w in words]
    def speaking(t):
        i = bisect.bisect_right(wst, t) - 1
        return i >= 0 and t <= words[i]["end"] + 0.3
    det, rows, prev_g, prev_s = None, [], None, None
    for i, img in enumerate(frames(a.video, a.fps)):
        t = round(i / a.fps, 3)
        if det is None:
            det = cv2.FaceDetectorYN.create(YUNET, "", (img.shape[1], img.shape[0]), 0.8)
        shot = bisect.bisect_right(cuts, t)
        g = cv2.cvtColor(cv2.resize(img, (320, img.shape[0] * 320 // img.shape[1])), cv2.COLOR_BGR2GRAY)
        r = {"t": t, "shot": shot, "luma": round(float(g.mean()) / 255, 3), "speaking": speaking(t) if words else None,
             "face": face(det, img), "cam": None, "grid_max": None, "grid_med": None}
        if prev_g is not None and prev_s == shot:
            r["cam"] = camera(prev_g, g)
            d = cv2.absdiff(cv2.resize(prev_g, (160, 90)), cv2.resize(g, (160, 90))).astype(float)
            f = r["face"]
            # cells overlapping the (enlarged) face box are ignored, so a moving head is not counted as a pop-in
            fx0, fx1 = ((f["cx"] - 0.8 * f["w"]) * 160, (f["cx"] + 0.8 * f["w"]) * 160) if f else (-1, -1)
            fy0, fy1 = ((f["cy"] - 0.8 * f["size"]) * 90, (f["cy"] + 0.8 * f["size"]) * 90) if f else (-1, -1)
            cells = [d[y:y + 23, x:x + 40].mean() for y in range(0, 90, 23) for x in range(0, 160, 40)
                     if not (x < fx1 and x + 40 > fx0 and y < fy1 and y + 23 > fy0)]
            if len(cells) >= 4:
                r["grid_max"], r["grid_med"] = round(max(cells), 2), round(float(np.median(cells)), 2)
        rows.append(r)
        prev_g, prev_s = g, shot
    if not rows:
        sys.exit("no frames decoded")
    dur = rows[-1]["t"]
    bounds = [0.0] + cuts + [dur + 1 / a.fps]
    ev = json.load(open(a.events, encoding="utf-8"))["events"] if a.events else []
    shots = []
    for k in range(len(bounds) - 1):
        fr = [r for r in rows if r["shot"] == k]
        if len(fr) < 3:
            continue
        t0, t1 = bounds[k], bounds[k + 1]
        lab = max((e for e in ev if e["t_start"] <= t0 + 0.05), key=lambda e: e["t_start"], default=None)
        fc = [r for r in fr if r["face"]]
        cams = [r["cam"] for r in fr if r["cam"]]
        s = {"t0": round(t0, 2), "t1": round(min(t1, dur), 2), "dur": round(min(t1, dur) - t0, 2),
             "layout": lab["layout"] if lab else None, "graphic_kind": lab["graphic_kind"] if lab else None,
             "face_share": round(len(fc) / len(fr), 2), "luma": med([r["luma"] for r in fr])}
        s["multi_face"] = bool(fc) and float(np.median([r["face"]["n"] for r in fc])) >= 2
        if len(fc) >= max(5, 0.6 * len(fr)) and not s["multi_face"]:
            # 5-frame median smoothing: YuNet landmark jitter alone gives ~1 deg (frontal) to ~3 deg (3/4 profile)
            sm = lambda v: [float(np.median(v[max(0, j - 2):j + 3])) for j in range(len(v))]
            roll = sm([r["face"]["roll"] for r in fc])
            yaw = sm([r["face"]["yaw"] for r in fc])
            pit = sm([r["face"]["pitch"] for r in fc])
            sec = len(fc) / a.fps
            rs, ys, ps = swings(roll, 3.0), swings(yaw, 0.1), swings(pit, 0.1)
            sp = [r["face"]["roll"] for r in fc if r["speaking"]]
            si = [r["face"]["roll"] for r in fc if r["speaking"] is False]
            s["head"] = {"roll_mean": round(float(np.mean(roll)), 2), "roll_std": round(float(np.std(roll)), 2),
                         "roll_range": round(float(np.percentile(roll, 95) - np.percentile(roll, 5)), 2),
                         "tilt_swings_per_s": round(len(rs) / sec, 2), "tilt_swing_deg_median": med(rs),
                         "turn_swings_per_s": round(len(ys) / sec, 2), "nod_swings_per_s": round(len(ps) / sec, 2),
                         "roll_std_speaking": round(float(np.std(sp)), 2) if len(sp) > 5 else None,
                         "roll_std_silent": round(float(np.std(si)), 2) if len(si) > 5 else None,
                         "face_size": med([r["face"]["size"] for r in fc]), "face_cx": med([r["face"]["cx"] for r in fc]),
                         "face_cy": med([r["face"]["cy"] for r in fc])}
        if len(cams) >= 3:
            zoom = float(np.prod([c["scale"] for c in cams]))
            span = len(cams) / a.fps
            tx = np.array([c["tx"] for c in cams]); ty = np.array([c["ty"] for c in cams])
            s["camera"] = {"zoom_pct_per_s": round((zoom ** (1 / span) - 1) * 100, 2),
                           "pan_pct_per_s": round(float(tx.sum()) / span * 100, 2), "tilt_pct_per_s": round(float(ty.sum()) / span * 100, 2),
                           "roll_deg_per_s": round(sum(c["rot"] for c in cams) / span, 2),
                           "shake_pct": round(float(np.std(np.diff(tx)) + np.std(np.diff(ty))) * 100, 3) if len(tx) > 3 else None,
                           "tracked_share": round(len(cams) / max(1, len(fr) - 1), 2)}
        pops, last = [], -9
        for r in fr:
            if r["grid_max"] is None or r["t"] - t0 < 0.3 or t1 - r["t"] < 0.3:
                continue
            if r["grid_max"] > 18 and r["grid_med"] < 4 and r["t"] - last > 0.5:
                pops.append(r["t"]); last = r["t"]
        s["pop_ins"] = pops
        lum = [r["luma"] for r in fr]
        s["flash"] = max(lum) - med(lum) > 0.25
        shots.append(s)
    face_shots = [s for s in shots if "head" in s]
    summary = {"frames": len(rows), "fps": a.fps, "shots": len(shots), "shots_with_face": len(face_shots),
               "pop_ins_total": sum(len(s["pop_ins"]) for s in shots)}
    by = {}
    for s in face_shots:
        by.setdefault(s["layout"] or "unknown", []).append(s)
    summary["head_by_layout"] = {k: {"n": len(v), "seconds": round(sum(x["dur"] for x in v), 1),
                                     **{f: med([x["head"][f] for x in v if x["head"][f] is not None]) for f in
                                        ("roll_std", "roll_range", "tilt_swings_per_s", "tilt_swing_deg_median",
                                         "turn_swings_per_s", "nod_swings_per_s", "roll_std_speaking", "roll_std_silent")}}
                                 for k, v in by.items()}
    cam = [s for s in shots if "camera" in s and s["camera"]["tracked_share"] > 0.6]
    summary["camera"] = {"n": len(cam), "push_in_shots": sum(s["camera"]["zoom_pct_per_s"] > 0.5 for s in cam),
                         "pull_out_shots": sum(s["camera"]["zoom_pct_per_s"] < -0.5 for s in cam),
                         "zoom_pct_per_s_median_of_moving": med([s["camera"]["zoom_pct_per_s"] for s in cam if abs(s["camera"]["zoom_pct_per_s"]) > 0.5]),
                         "shake_pct_median": med([s["camera"]["shake_pct"] for s in cam if s["camera"]["shake_pct"] is not None])}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump({"summary": summary, "shots": shots}, open(a.out, "w", encoding="utf-8"), indent=1)
    json.dump(rows, open(a.out.replace(".json", "_frames.json"), "w"), separators=(",", ":"))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
