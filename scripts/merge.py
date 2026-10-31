"""Merge pass-1 windows into one clean event log per video.

- Anchored events get the measured time (never Gemini's).
- spoken_trigger is replaced by the real words from the word-timed transcript (window -1 s .. +2 s),
  and the nearest number word in that span is recorded, so "graph appears on a spoken number" is countable.
- Duplicates (same anchor + same event_type) are dropped.

  python merge.py --raw <pack>/raw_v2 --id ID --transcript ID.json --out <pack>/events/ID.json
"""
import argparse, glob, json, os, re

NUM = re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|percent|half|double)\b", re.I)


def words_between(words, a, b):
    return [w for w in words if w["end"] >= a and w["start"] <= b]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    words = json.load(open(a.transcript, encoding="utf-8"))
    windows, events, seen, skipped = [], [], set(), []
    for path in sorted(glob.glob(os.path.join(a.raw, f"{a.id}_*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        m = d["_meta"]
        windows.append({k: d[k] for k in ("segment_summary", "music_present", "music_character", "dominant_layout")}
                       | {"start": m["start"], "end": m["end"], "finish_reason": m["finish_reason"]})
        skipped += d.get("skipped_anchors", [])
        for e in d["events"]:
            aid = e.get("anchor_id", "none")
            if aid in m["anchors"]:
                e["t_start"] = m["anchors"][aid]
                e["anchored"] = True
            else:
                e["anchored"] = False
            key = (aid, e["event_type"]) if e["anchored"] else (round(e["t_start"], 1), e["event_type"])
            if key in seen:
                continue
            seen.add(key)
            span = words_between(words, e["t_start"] - 1, e["t_start"] + 2)
            e["gemini_trigger"] = e.pop("spoken_trigger", "")
            e["spoken_trigger"] = " ".join(w["text"] for w in span)
            nums = [w for w in words_between(words, e["t_start"] - 3, e["t_start"] + 3) if NUM.search(w["text"])]
            e["number_word_lag"] = round(e["t_start"] - min(nums, key=lambda w: abs(w["start"] - e["t_start"]))["start"], 2) if nums else None
            events.append(e)
    events.sort(key=lambda e: e["t_start"])
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"id": a.id, "windows": windows, "skipped_anchors": skipped, "events": events},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(a.id, len(events), "events,", sum(e["anchored"] for e in events), "anchored,", len(skipped), "skipped")


if __name__ == "__main__":
    main()
