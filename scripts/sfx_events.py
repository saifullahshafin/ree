"""Event-centred SFX test (replaces blind transient scanning, which on the first pack matched visual edits no
better than random times and picked up drum hits).

For every anchored visual event it measures, on the music+SFX stem, the rise of the loudest 50 ms in
[t-0.7, t+0.5] over the bed level in [t-2.5, t-1.0]. The same is measured at random control times. Gemini's
audio_cue labels are then checked against the measurement: an SFX label is corroborated when its rise clears
the 90th percentile of the controls. Per corroborated event it records peak offset, length above bed and
brightness, so each SFX type gets measured timing and character.

Runs on the VM (needs the stem):
  python sfx_events.py --events events/ID.json --stem sep/htdemucs/ID/no_vocals.wav --out sfx_ev/ID.json
"""
import argparse, json, random
import numpy as np
import librosa

HOP = 256


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--stem", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--controls", type=int, default=400)
    a = ap.parse_args()
    d = json.load(open(a.events, encoding="utf-8"))
    y, sr = librosa.load(a.stem, sr=44100, mono=True)
    lvl = 20 * np.log10(np.maximum(librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0], 1e-6))
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP)[0]
    fps = sr / HOP
    w50 = max(1, int(0.05 * fps))
    sm = np.convolve(lvl, np.ones(w50) / w50, mode="same")

    def probe(t):
        i0, i1 = int((t - 0.7) * fps), int((t + 0.5) * fps)
        b0, b1 = int((t - 2.5) * fps), int((t - 1.0) * fps)
        if b0 < 0 or i1 >= len(sm):
            return None
        bed = float(np.median(sm[b0:b1]))
        k = i0 + int(np.argmax(sm[i0:i1]))
        rise = float(sm[k] - bed)
        above = sm[i0:i1] > bed + 6
        on = k
        while on > i0 and sm[on - 1] > bed + 3:
            on -= 1
        attack_ms, long_ms = round(1000 * (k - on) / fps), round(1000 * above.sum() / fps)
        # free shape classes (no model listening): sharp short hit vs a swell that builds into the peak
        shape = ("click" if cent[k] > 3500 else "pop") if long_ms < 180 and attack_ms < 60 else \
                "whoosh_swell" if attack_ms >= 80 else "hit_long"
        return {"rise_db": round(rise, 1), "peak_offset_ms": round((k / fps - t) * 1000), "attack_ms": attack_ms,
                "shape": shape,
                "ms_above_bed6": round(1000 * above.sum() / fps), "centroid_hz": int(cent[k]), "bed_db": round(bed, 1)}

    dur = len(y) / sr
    random.seed(0)
    ev_times = [e["t_start"] for e in d["events"]]
    ctrl = []
    while len(ctrl) < a.controls:
        t = random.uniform(3, dur - 1)
        if min(abs(t - x) for x in ev_times) > 1.5:
            p = probe(t)
            if p:
                ctrl.append(p["rise_db"])
    thr = float(np.percentile(ctrl, 90))
    rows = []
    for e in d["events"]:
        if not e["anchored"]:
            continue
        p = probe(e["t_start"])
        if p:
            rows.append({"t": e["t_start"], "event_type": e["event_type"], "motion_in": e["motion_in"],
                         "graphic_kind": e["graphic_kind"], "gemini_audio": e["audio_cue"], **p,
                         "sfx_measured": p["rise_db"] >= thr})
    by = {}
    for lab in sorted({r["gemini_audio"] for r in rows}):
        rs = [r for r in rows if r["gemini_audio"] == lab]
        by[lab] = {"n": len(rs), "median_rise_db": round(float(np.median([r["rise_db"] for r in rs])), 1),
                   "share_over_control_p90": round(sum(r["sfx_measured"] for r in rs) / len(rs), 2)}
    out = {"id": d["id"], "control_rise_db": {"median": round(float(np.median(ctrl)), 1), "p90": round(thr, 1)},
           "by_gemini_label": by, "events": rows}
    json.dump(out, open(a.out, "w"), indent=1)
    print(d["id"], json.dumps({k: out[k] for k in ("control_rise_db", "by_gemini_label")}))


if __name__ == "__main__":
    main()
