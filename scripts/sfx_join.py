"""Join measured sound effects to visual events: which edits get a sound, which sound, and how tightly synced.

Each SFX (named by sfx_name.py) is matched to the nearest anchored visual event within -0.7 .. +0.5 s of the
SFX peak. Gemini's own audio_cue labels on visual events are kept, so every pairing is tagged:
  confirmed      meter found a transient and Gemini heard an SFX on that event
  measured_only  meter found it, Gemini did not label it (often whooshes into cuts)
  heard_only     Gemini heard an SFX, the meter found nothing above the bed (quiet or under music)

  python sfx_join.py --events <pack>/events --sfx <pack>/sfx_types.json --out <pack>/sound_design.json
"""
import argparse, glob, json, os
import statistics as st
from collections import Counter, defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--sfx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--before", type=float, default=0.7)
    ap.add_argument("--after", type=float, default=0.5)
    a = ap.parse_args()
    sx = json.load(open(a.sfx, encoding="utf-8"))
    types = {int(k): v for k, v in sx["types"].items()}
    by_vid = defaultdict(list)
    for s in sx["sfx"]:
        t = types.get(s["cluster"], {}).get("sfx_type", "other")
        if t in ("music_hit_not_sfx", "speech_leak_not_sfx"):
            continue
        by_vid[s["video"]].append(dict(s, sfx_type=t))
    pairs, offsets = [], defaultdict(list)
    per_event_kind, tag_count = defaultdict(Counter), Counter()
    sfx_per_min = {}
    for path in sorted(glob.glob(os.path.join(a.events, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        ev = [e for e in d["events"] if e["anchored"]]
        sfx = by_vid.get(d["id"], [])
        used = set()
        for e in ev:
            near = [s for s in sfx if -a.before <= s["t"] - e["t_start"] <= a.after and id(s) not in used]
            heard = e["audio_cue"].startswith("sfx")
            key = f"{e['event_type']}|{e['motion_in']}"
            if near:
                s = min(near, key=lambda s: abs(s["t"] - e["t_start"]))
                used.add(id(s))
                tag = "confirmed" if heard else "measured_only"
                offsets[s["sfx_type"]].append(round((s["t"] - e["t_start"]) * 1000))
                per_event_kind[key][s["sfx_type"]] += 1
                pairs.append({"video": d["id"], "t": e["t_start"], "event_type": e["event_type"], "motion_in": e["motion_in"],
                              "graphic_kind": e["graphic_kind"], "sfx_type": s["sfx_type"], "tag": tag,
                              "sfx_start_offset_ms": round((s["start"] - e["t_start"]) * 1000),
                              "sfx_peak_offset_ms": round((s["t"] - e["t_start"]) * 1000), "sfx_jump_db": s["jump_db"]})
            elif heard:
                tag = "heard_only"
                per_event_kind[key][e["audio_cue"] + "(heard)"] += 1
                pairs.append({"video": d["id"], "t": e["t_start"], "event_type": e["event_type"], "motion_in": e["motion_in"],
                              "graphic_kind": e["graphic_kind"], "sfx_type": e["audio_cue"], "tag": tag})
            else:
                tag = "silent"
                per_event_kind[key]["none"] += 1
            tag_count[tag] += 1
        orphan = [s for s in sfx if id(s) not in used]
        dur = d["windows"][-1]["end"] / 60
        sfx_per_min[d["id"]] = {"sfx_measured_per_min": round(len(sfx) / dur, 2),
                                "sfx_without_visual_event": len(orphan),
                                "orphan_types": Counter(s["sfx_type"] for s in orphan).most_common()}
    out = {
        "tags": dict(tag_count),
        "sfx_types": {i: {k: v for k, v in t.items() if k != "exemplars"} for i, t in types.items()},
        "sync_peak_offset_ms_by_type": {k: {"median": st.median(v), "p25": sorted(v)[len(v) // 4], "p75": sorted(v)[3 * len(v) // 4],
                                            "n": len(v)} for k, v in offsets.items() if v},
        "sound_by_event_and_motion": {k: dict(v.most_common()) for k, v in sorted(per_event_kind.items(), key=lambda kv: -sum(kv[1].values()))},
        "per_video": sfx_per_min,
        "pairs": pairs,
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: out[k] for k in ("tags", "sync_peak_offset_ms_by_type")}, indent=1))


if __name__ == "__main__":
    main()
