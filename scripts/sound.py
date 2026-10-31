"""Measured sound layer: music bed, ducking and sound effects (runs on the ARM VM, venv-audio).

Demucs splits the original full-band audio into the voice and everything else (music + SFX). On the
non-voice stem:
- music bed: level curve (1 s smoothing), on/off segments, change points (timbre novelty), tempo per segment
- ducking: bed level while he speaks vs in pauses of 0.4 s or more inside the same music segment
- SFX: transients that jump well above the local bed, each with acoustic features (attack, length,
  brightness, noisiness, pitch direction) so they can be clustered into whoosh / pop / click / ding / riser
Word timings (Parakeet transcript) mark when he speaks.

  python sound.py --audio full/ID.m4a --words out/ID/transcript.json --work sep --out sound/ID.json
"""
import argparse, json, os, subprocess
import numpy as np
import librosa

HOP = 512


def separate(audio, work):
    """Demucs htdemucs through its Python API (the CLI's torchaudio save needs torchcodec on new torch)."""
    name = os.path.splitext(os.path.basename(audio))[0]
    d = os.path.join(work, "htdemucs", name)
    bed, voice = os.path.join(d, "no_vocals.wav"), os.path.join(d, "vocals.wav")
    if os.path.exists(bed):
        return bed, voice
    import torch, soundfile as sf
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    os.makedirs(d, exist_ok=True)
    # Chunked: a whole 28 min video in one pass needs about 2.4 GB for the output alone and drove a shared
    # 23 GB VM into swap (2026-10-31). 120 s chunks with 1 s of context each side, trimmed, keep it near 200 MB.
    sr, chunk, pad = 44100, 120.0, 1.0
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                                 capture_output=True, text=True, check=True).stdout)
    model = get_model("htdemucs")
    model.eval()
    v = model.sources.index("vocals")
    torch.set_num_threads(int(os.environ.get("DEMUCS_THREADS", "3")))
    with sf.SoundFile(voice + ".part", "w", sr, 2, format="WAV") as fv, \
            sf.SoundFile(bed + ".part", "w", sr, 2, format="WAV") as fb:
        s = 0.0
        while s < total:
            a0 = max(0.0, s - pad)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a0:.3f}", "-t", f"{chunk + 2 * pad:.3f}", "-i", audio,
                                  "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"], capture_output=True, check=True).stdout
            wav = torch.from_numpy(np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy())
            ref = wav.mean(0)
            mu, sd = ref.mean(), ref.std() + 1e-8
            with torch.no_grad():
                out = apply_model(model, ((wav - mu) / sd)[None], device="cpu", shifts=1, split=True, overlap=0.25,
                                  progress=False)[0] * sd + mu
            lo = int(round((s - a0) * sr))
            hi = lo + int(round(min(chunk, total - s) * sr))
            fv.write(out[v][:, lo:hi].T.numpy())
            fb.write((out.sum(0) - out[v])[:, lo:hi].T.numpy())
            del wav, out
            s += chunk
    os.replace(voice + ".part", voice)
    os.replace(bed + ".part", bed)
    return bed, voice


def speech_mask(words, n, sr):
    m = np.zeros(n, bool)
    for w in words:
        a, b = int(w["start"] * sr / HOP), int(w["end"] * sr / HOP) + 1
        m[a:b] = True
    return m


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-6))


def segments(flag, sr, min_len=2.0):
    out, start = [], None
    for i, f in enumerate(np.append(flag, False)):
        if f and start is None:
            start = i
        elif not f and start is not None:
            a, b = start * HOP / sr, i * HOP / sr
            if b - a >= min_len:
                out.append([round(a, 2), round(b, 2)])
            start = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--music-floor", type=float, default=-50, help="dBFS: bed below this counts as no music")
    ap.add_argument("--sfx-jump", type=float, default=9, help="dB a transient must rise above the local bed")
    a = ap.parse_args()
    words = json.load(open(a.words))
    words = words if isinstance(words, list) else words["words"]
    bed_path, voice_path = separate(a.audio, a.work)
    y, sr = librosa.load(bed_path, sr=44100, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    lvl = db(rms)
    fps = sr / HOP
    smooth = np.convolve(lvl, np.ones(int(fps)) / int(fps), mode="same")          # 1 s bed level
    speech = speech_mask(words, len(lvl), sr)

    # music bed
    music_on = smooth > a.music_floor
    music_segs = segments(music_on, sr, 3.0)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=13)
    nov = librosa.onset.onset_strength(S=librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=sr, hop_length=HOP)),
                                       sr=sr, hop_length=HOP, aggregate=np.median)
    music = []
    for s, e in music_segs:
        i, j = int(s * fps), int(e * fps)
        seg = y[i * HOP:j * HOP]
        tempo = float(np.atleast_1d(librosa.beat.beat_track(y=seg, sr=sr, hop_length=HOP)[0])[0]) if e - s > 8 else None
        sp, pa = speech[i:j], ~speech[i:j]
        # pauses: runs of no speech of at least 0.4 s
        pause = np.zeros_like(pa)
        run = 0
        for k, p in enumerate(pa):
            run = run + 1 if p else 0
            if run >= int(0.4 * fps):
                pause[k - run + 1:k + 1] = True
        duck = float(np.median(smooth[i:j][pause]) - np.median(smooth[i:j][sp])) if pause.any() and sp.any() else None
        music.append({"start": s, "end": e, "level_db_median": round(float(np.median(smooth[i:j])), 1),
                      "tempo_bpm": round(tempo, 1) if tempo else None,
                      "duck_db": round(duck, 1) if duck is not None else None,
                      "timbre": [round(float(v), 1) for v in mfcc[:, i:j].mean(axis=1)]})
    # timbre change points inside music (a new track or a section change)
    changes = []
    for s, e in music_segs:
        i, j = int(s * fps), int(e * fps)
        if j - i < fps * 20:
            continue
        bounds = librosa.segment.agglomerative(mfcc[:, i:j], max(2, int((e - s) // 45) + 1))
        changes += [round(s + b / fps, 2) for b in bounds[1:]]

    # sound effects: fast rises well above the local bed
    local = np.array([np.median(lvl[max(0, k - int(fps * 1.5)):k + int(fps * 1.5)]) for k in range(len(lvl))])
    peaks = librosa.util.peak_pick(nov, pre_max=5, post_max=5, pre_avg=20, post_avg=20, delta=0.5, wait=int(fps * 0.15))
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP)[0]
    flat = librosa.feature.spectral_flatness(y=y, hop_length=HOP)[0]
    sfx = []
    for p in peaks:
        top = lvl[p:p + int(fps * 0.1)].max()
        jump = top - local[p]
        if jump < a.sfx_jump or top < a.music_floor:
            continue
        k = p
        while k < len(lvl) - 1 and lvl[k] > local[p] + 6 and k - p < fps * 3:
            k += 1
        start = p
        while start > 0 and lvl[start - 1] > local[p] + 3 and p - start < fps * 1.5:
            start -= 1          # whooshes and risers swell in before the onset
        span = slice(start, max(k, p + 2))
        c = cent[span]
        sfx.append({"t": round(p / fps, 3), "start": round(start / fps, 3), "dur": round((max(k, p + 2) - start) / fps, 3),
                    "attack": round((p - start) / fps, 3), "peak_db": round(float(top), 1), "jump_db": round(float(jump), 1),
                    "centroid_hz": round(float(c.mean())), "pitch_slope": round(float(np.polyfit(np.arange(len(c)), c, 1)[0] * fps), 1) if len(c) > 2 else 0.0,
                    "flatness": round(float(flat[span].mean()), 3), "during_speech": bool(speech[p])})
    # mix loudness of the original (ffmpeg ebur128)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.audio, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    lufs = next((float(l.split()[1]) for l in tail.splitlines() if l.strip().startswith("I:")), None)
    lra = next((float(l.split()[1]) for l in tail.splitlines() if l.strip().startswith("LRA:")), None)
    out = {"audio": os.path.basename(a.audio), "integrated_lufs": lufs, "loudness_range_lu": lra,
           "music_share": round(sum(e - s for s, e in music_segs) / (len(y) / sr), 3),
           "music_segments": music, "music_changes": changes, "sfx": sfx}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(os.path.basename(a.audio), "music", out["music_share"], "segments", len(music), "sfx", len(sfx), "LUFS", lufs)


if __name__ == "__main__":
    main()
