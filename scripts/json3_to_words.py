"""Convert YouTube auto-caption json3 (per-word tOffsetMs) into the REE transcript word list.

Used instead of Parakeet because this creator speaks Hindi (Parakeet is English only).
Word start = event start + word offset; word end = next word's start, capped at the event end.
Usage: python -I json3_to_words.py <in.json3> <out.json> [duration_s]
"""
import json, sys


def convert(path):
    d = json.load(open(path, encoding="utf-8"))
    raw = []
    for e in d.get("events", []):
        t0, dur = e.get("tStartMs", 0), e.get("dDurationMs", 0)
        for s in e.get("segs", []):
            txt = s.get("utf8", "").strip()
            if not txt:
                continue
            raw.append((t0 + s.get("tOffsetMs", 0), t0 + dur, txt))
    raw.sort(key=lambda w: w[0])
    words = []
    for i, (st, ev_end, txt) in enumerate(raw):
        nxt = raw[i + 1][0] if i + 1 < len(raw) else ev_end
        en = min(nxt, ev_end) if nxt > st else ev_end
        words.append({"id": f"w{i}", "text": txt, "start": round(st / 1000, 3), "end": round(max(en, st + 1) / 1000, 3)})
    return words


if __name__ == "__main__":
    words = convert(sys.argv[1])
    json.dump(words, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else None
    print(f"{len(words)} words, last ends {words[-1]['end']:.1f}s" + (f" / duration {dur:.1f}s" if dur else ""))
