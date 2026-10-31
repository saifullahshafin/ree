"""Fast sound pass: separate only short windows instead of whole videos (minutes, not hours).

Whole-video Demucs on a 4-core ARM CPU runs at about 1.3x real time (2+ hours for 2 hours of footage). For a
style pack three answers are enough, and each needs only a few windows:
- music share and level: N random 10 s windows (music present? bed level? voice level?)
- whoosh / pop reality: windows centred on edits the labels say carry a sound, plus random edits as controls;
  each gets a 2 s spectrogram of the music+SFX stem with a red line at the edit, for the agent to read
Integrated loudness comes from ffmpeg ebur128 on the original (seconds).

  python sound_quick.py --audio full/ID.m4a --events events/ID.json --out quick/ID [--random 20 --per-label 8]
Writes quick/ID/summary.json and quick/ID/spec_*.png (spectrograms named with label and time).
"""
import argparse, json, os, random, subprocess
import numpy as np
import torch
from demucs.pretrained import get_model
from demucs.apply import apply_model

SR = 44100


def clip(audio, t0, dur):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t0):.3f}", "-t", f"{dur:.3f}", "-i", audio,
                          "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return torch.from_numpy(np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy())


def separate(model, wav):
    ref = wav.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        out = apply_model(model, ((wav - mu) / sd)[None], device="cpu", shifts=1, split=True, overlap=0.25,
                          progress=False)[0] * sd + mu
    v = model.sources.index("vocals")
    return out[v].mean(0).numpy(), (out.sum(0) - out[v]).mean(0).numpy()


def db(x):
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))


def spectro(bed, path, t_center_in_clip):
    a = int((t_center_in_clip - 1) * SR); b = int((t_center_in_clip + 1) * SR)
    seg = bed[max(0, a):b].astype(np.float32)
    tmp = path + ".raw"
    seg.tofile(tmp)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", tmp, "-lavfi",
                    "showspectrumpic=s=360x140:legend=0:scale=log:fscale=log:color=intensity,"
                    "drawbox=x=iw/2:y=0:w=1:h=ih:color=red", path], check=True)
    os.remove(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--random", type=int, default=20, help="random 10 s windows for music share and level")
    ap.add_argument("--per-label", type=int, default=8, help="edits per sound label to check on spectrograms")
    ap.add_argument("--threads", type=int, default=3)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    os.makedirs(a.out, exist_ok=True)
    d = json.load(open(a.events, encoding="utf-8"))
    dur = d["windows"][-1]["end"]
    model = get_model("htdemucs"); model.eval()
    random.seed(0)
    # music share and level from random windows
    rows = []
    for t0 in sorted(random.uniform(5, dur - 15) for _ in range(a.random)):
        voice, bed = separate(model, clip(a.audio, t0, 10))
        rows.append({"t": round(t0, 1), "bed_db": round(db(bed), 1), "voice_db": round(db(voice), 1)})
    floor = -50.0
    music = [r for r in rows if r["bed_db"] > floor]
    # sound checks around labelled edits, plus controls
    ev = [e for e in d["events"] if e.get("anchored")]
    picks = []
    for lab in ("sfx_whoosh", "sfx_pop", "sfx_click_or_type"):
        cand = [e for e in ev if e["audio_cue"] == lab]
        picks += [(lab, e) for e in random.sample(cand, min(a.per_label, len(cand)))]
    none = [e for e in ev if e["audio_cue"] == "none"]
    picks += [("none", e) for e in random.sample(none, min(a.per_label, len(none)))]
    checks = []
    for lab, e in picks:
        t = e["t_start"]
        _, bed = separate(model, clip(a.audio, t - 2, 4))
        name = f"spec_{lab.replace('sfx_', '')}_{t:07.2f}.png"
        spectro(bed, os.path.join(a.out, name), 2.0)
        checks.append({"file": name, "label": lab, "t": t, "event_type": e["event_type"], "motion_in": e["motion_in"]})
    summary = {"windows": rows, "music_floor_db": floor,
               "music_share_est": round(len(music) / len(rows), 2),
               "bed_db_median_when_music": round(float(np.median([r["bed_db"] for r in music])), 1) if music else None,
               "voice_minus_bed_db_median": round(float(np.median([r["voice_db"] - r["bed_db"] for r in music])), 1) if music else None,
               "checks": checks}
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    print(os.path.basename(a.audio), "music share", summary["music_share_est"], "bed", summary["bed_db_median_when_music"],
          "voice-bed", summary["voice_minus_bed_db_median"], "checks", len(checks))


if __name__ == "__main__":
    main()
