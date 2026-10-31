"""Group measured sound effects by acoustic shape, then let Gemini listen to exemplars and name each group.

Runs where the separated stems are (ARM VM, venv-audio + google-genai not needed there): use --cut to write
exemplar clips on the VM, copy the clips folder back, then run --name on the laptop.

  VM:      python sfx_name.py --cut --sound sound --stems sep/htdemucs --clips sfx_clips
  laptop:  python sfx_name.py --name --sound <pack>/sound --clips <pack>/sfx_clips --out <pack>/sfx_types.json
"""
import argparse, glob, json, os

import numpy as np

K = 7


def features(s):
    return [np.log(s["dur"] + 0.02), np.log(s["attack"] + 0.02), np.log(s["centroid_hz"] + 50),
            np.sign(s["pitch_slope"]) * np.log1p(abs(s["pitch_slope"]) / 100), s["jump_db"] / 10]


def load(sound_dir):
    rows = []
    for p in sorted(glob.glob(os.path.join(sound_dir, "*.json"))):
        d = json.load(open(p))
        vid = os.path.splitext(d["audio"])[0]
        seen = set()
        for s in d["sfx"]:
            if s["start"] in seen:      # one swell detected twice keeps its strongest peak only
                continue
            seen.add(s["start"])
            rows.append(dict(s, video=vid))
    return rows


def kmeans(x, k, iters=60, seed=0):
    rng = np.random.default_rng(seed)
    c = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((x[:, None] - c[None]) ** 2).sum(-1), 1)
        c = np.array([x[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
    return lab, c


def cluster(rows):
    x = np.array([features(r) for r in rows])
    x = (x - x.mean(0)) / (x.std(0) + 1e-6)
    lab, c = kmeans(x, K)
    for r, l in zip(rows, lab):
        r["cluster"] = int(l)
    # exemplars: the 3 loudest-above-bed members nearest their centre
    ex = {}
    for i in range(K):
        idx = [j for j in range(len(rows)) if lab[j] == i]
        idx.sort(key=lambda j: ((x[j] - c[i]) ** 2).sum() - 0.3 * rows[j]["jump_db"] / 10)
        ex[i] = [rows[j] for j in idx[:3]]
    return rows, ex


def cut(a):
    import soundfile as sf
    rows, ex = cluster(load(a.sound))
    os.makedirs(a.clips, exist_ok=True)
    for i, members in ex.items():
        for n, r in enumerate(members):
            y, sr = sf.read(os.path.join(a.stems, r["video"], "no_vocals.wav"),
                            start=int(max(0, r["start"] - 0.3) * 44100), stop=int((r["start"] + r["dur"] + 0.5) * 44100))
            sf.write(os.path.join(a.clips, f"c{i}_{n}_{r['video']}_{r['t']:.2f}.wav"), y, sr)
    json.dump(rows, open(os.path.join(a.clips, "sfx_clustered.json"), "w"), indent=0)
    print({i: sum(r["cluster"] == i for r in rows) for i in range(K)})


NAME = {"type": "OBJECT", "properties": {
    "sfx_type": {"type": "STRING", "enum": ["whoosh", "swoosh_short", "pop", "click", "typing", "ding_chime", "riser",
                                            "impact_hit", "swipe_paper", "camera_shutter", "notification",
                                            "music_hit_not_sfx", "speech_leak_not_sfx", "other"]},
    "character": {"type": "STRING", "description": "pitch, brightness, length, softness, e.g. 'soft airy whoosh, falling, 400 ms'"},
    "consistent": {"type": "BOOLEAN", "description": "are the clips the same kind of sound?"},
    "library_search_terms": {"type": "STRING", "description": "terms to find a matching sound in a SFX library"}},
    "required": ["sfx_type", "character", "consistent", "library_search_terms"]}


def name(a):
    from google import genai
    from google.genai import types
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from watch import env
    client = genai.Client(vertexai=True, api_key=env("VERTEX_API_KEY"))
    rows = json.load(open(os.path.join(a.clips, "sfx_clustered.json")))
    out = {}
    for i in range(K):
        files = sorted(glob.glob(os.path.join(a.clips, f"c{i}_*.wav")))
        if not files:
            continue
        parts = []
        for f in files:
            parts.append(types.Part.from_text(text=os.path.basename(f)))
            parts.append(types.Part.from_bytes(data=open(f, "rb").read(), mime_type="audio/wav"))
        parts.append("These clips are from the music-and-effects stem of a YouTube video (voice removed). Each clip "
                     "starts 0.3 s before a detected sound. Identify the sound effect they share.")
        r = client.models.generate_content(model=a.model, contents=parts, config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=NAME, temperature=0.1))
        members = [x for x in rows if x["cluster"] == i]
        out[i] = json.loads(r.text) | {"count": len(members),
                                       "median_dur_s": round(float(np.median([m["dur"] for m in members])), 3),
                                       "median_attack_s": round(float(np.median([m["attack"] for m in members])), 3),
                                       "median_centroid_hz": int(np.median([m["centroid_hz"] for m in members])),
                                       "median_jump_db": round(float(np.median([m["jump_db"] for m in members])), 1),
                                       "exemplars": [os.path.basename(f) for f in files]}
        print(i, out[i]["sfx_type"], out[i]["count"], out[i]["character"][:70], flush=True)
    json.dump({"types": out, "sfx": rows}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", action="store_true")
    ap.add_argument("--name", action="store_true")
    ap.add_argument("--sound", default="sound")
    ap.add_argument("--stems", default="sep/htdemucs")
    ap.add_argument("--clips", default="sfx_clips")
    ap.add_argument("--out", default="sfx_types.json")
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    a = ap.parse_args()
    cut(a) if a.cut else name(a)
