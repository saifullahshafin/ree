"""Put Gemini (AGY) transcript text on YouTube caption word times.

Gemini text is better (English words in Latin, English clips heard right) but its times drift; the YouTube
auto-caption words have good times. Words are matched in order (difflib on normalised tokens); matched Gemini
words take the YouTube word's times, unmatched ones are spread evenly between the neighbouring matches.
Usage: python align_words.py <pack> <video_id>
Reads data/agy/<id>/*.json + data/transcripts_yt/<id>.json, writes data/transcripts/<id>.json.
"""
import difflib, glob, json, os, re, sys

PUNCT = r"[\s.,!?\"'“”‘’()\[\]{}:;।॥…\-–—]"


def norm(t):
    return re.sub(PUNCT, "", t.lower())


def main():
    pack, vid = sys.argv[1], sys.argv[2]
    yt = json.load(open(os.path.join(pack, "data", "transcripts_yt", vid + ".json"), encoding="utf-8"))
    yt = [w for w in yt if norm(w["text"]) and not w["text"].startswith("[")]
    gem = []
    for p in sorted(glob.glob(os.path.join(pack, "data", "agy", vid, "[0-9]*.json"))):
        for seg in json.load(open(p, encoding="utf-8")):
            gem += [t for t in seg["text"].split() if norm(t)]
    a, b = [norm(w["text"]) for w in yt], [norm(t) for t in gem]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    times = [None] * len(gem)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            w = yt[blk.a + k]
            times[blk.b + k] = (w["start"], w["end"])
    matched = sum(t is not None for t in times)
    # spread unmatched words between neighbouring anchors
    anchors = [i for i, t in enumerate(times) if t]
    end_all = yt[-1]["end"]
    out, prev = [], None
    for i, tok in enumerate(gem):
        if times[i] is None:
            lo = max((j for j in anchors if j < i), default=None)
            hi = min((j for j in anchors if j > i), default=None)
            t0 = times[lo][1] if lo is not None else 0.0
            t1 = times[hi][0] if hi is not None else end_all
            n = (hi if hi is not None else len(gem)) - (lo if lo is not None else -1)
            k = i - (lo if lo is not None else -1)
            st = t0 + (t1 - t0) * (k - 1) / max(n - 1, 1)
            times[i] = (round(st, 3), round(st + (t1 - t0) / max(n - 1, 1), 3))
        st, en = times[i]
        if prev is not None and st < prev:
            st = prev
        en = max(en, st + 0.01)
        out.append({"id": f"w{i}", "text": tok, "start": round(st, 3), "end": round(en, 3)})
        prev = st
    json.dump(out, open(os.path.join(pack, "data", "transcripts", vid + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)
    print(f"{vid}: {len(gem)} Gemini words, {matched} matched to YouTube times ({100 * matched / max(len(gem), 1):.0f}%), "
          f"last ends {out[-1]['end']:.1f}s")


if __name__ == "__main__":
    main()
