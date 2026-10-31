"""Trigger and rhythm patterns from merged events (the 'when and why' evidence for EDIT_RULES.md).

- layout transitions: from -> to, with the talk beat and energy at the switch, and hold time of the new state
- energy x edit: what the edit does at each speaker energy (event mix, graphic share, events per minute)
- pace curve: events per minute by tenth of the video
- spoken lead-ins: words most often spoken in the 2 s before a graphic appears (vs their base rate)
Only anchored events are used.

  python patterns.py --events <pack>/events --transcripts <pack>/data/transcripts --out <pack>/patterns.json
"""
import argparse, glob, json, os, re
import statistics as st
from collections import Counter, defaultdict

STOP = set("the a an and to of i it is that you in this for on so be as we with my me are was have like just".split())
STOP |= set("है हैं था थे थी के की का में और तो से को ये यह वो वह कि एक भी नहीं पर ही जो हम आप मैं इस उस कर".split())  # Hindi packs


def norm(text):
    # Strip punctuation only, so non-Latin words (Hindi etc.) keep their letters and vowel signs.
    return re.sub(r"[\s.,!?\"'“”‘’()\[\]{}:;।॥…\-–—]", "", text.lower())


def med(xs):
    return round(st.median(xs), 2) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--transcripts", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    trans = Counter()
    trans_beats, trans_energy, holds = defaultdict(Counter), defaultdict(Counter), defaultdict(list)
    energy_mix, energy_time = defaultdict(Counter), Counter()
    deciles = [[] for _ in range(10)]
    lead, base, n_graphics = Counter(), Counter(), 0
    for path in sorted(glob.glob(os.path.join(a.events, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        ev = [e for e in d["events"] if e["anchored"]]
        dur = d["windows"][-1]["end"]
        words = json.load(open(os.path.join(a.transcripts, d["id"] + ".json"), encoding="utf-8"))
        for w in words:
            t = norm(w["text"])
            if t and t not in STOP:
                base[t] += 1
        counts = [0] * 10
        for e, nxt in zip(ev, ev[1:] + [None]):
            counts[min(9, int(10 * e["t_start"] / dur))] += 1
            span = (nxt["t_start"] if nxt else dur) - e["t_start"]
            energy_mix[e["speaker_energy"]][e["event_type"]] += 1
            energy_time[e["speaker_energy"]] += span
            if e["graphic_kind"] != "none":
                n_graphics += 1
                for w in words:
                    if e["t_start"] - 2 <= w["start"] < e["t_start"]:
                        t = norm(w["text"])
                        if t and t not in STOP:
                            lead[t] += 1
        prev = None
        for e, nxt in zip(ev, ev[1:] + [None]):
            if prev and e["layout"] != prev:
                k = f"{prev} -> {e['layout']}"
                trans[k] += 1
                trans_beats[k][e["talk_beat"]] += 1
                trans_energy[k][e["speaker_energy"]] += 1
            if not prev or e["layout"] != prev:
                end = next((x["t_start"] for x in ev if x["t_start"] > e["t_start"] and x["layout"] != e["layout"]), dur)
                holds[e["layout"]].append(end - e["t_start"])
            prev = e["layout"]
        for i in range(10):
            deciles[i].append(counts[i] / (dur / 600))
    total_lead = sum(lead.values()) or 1
    total_base = sum(base.values()) or 1
    lift = {w: round((c / total_lead) / (base[w] / total_base), 1) for w, c in lead.items() if c >= 4 and base[w] >= 8}
    out = {
        "layout_transitions": [{"transition": k, "count": n, "talk_beats": dict(trans_beats[k].most_common(4)),
                                "energy": dict(trans_energy[k].most_common(3))} for k, n in trans.most_common(16)],
        "layout_hold_s": {k: {"median": med(v), "p25": round(sorted(v)[len(v) // 4], 2), "p75": round(sorted(v)[3 * len(v) // 4], 2),
                              "n": len(v)} for k, v in holds.items() if len(v) >= 3},
        "energy_vs_edit": {k: {"events_per_min": round(sum(v.values()) / (energy_time[k] / 60), 1) if energy_time[k] else None,
                               "mix": dict(v.most_common(5))} for k, v in energy_mix.items()},
        "pace_curve_events_per_min_by_tenth": [round(st.mean(x), 1) for x in deciles],
        "lead_in_words_before_graphics": sorted(lift.items(), key=lambda kv: -kv[1])[:25],
        "graphics_counted": n_graphics,
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: out[k] for k in ("layout_hold_s", "pace_curve_events_per_min_by_tenth", "lead_in_words_before_graphics")}, indent=1)[:2500])
    for t in out["layout_transitions"][:12]:
        print(t)
    for k, v in out["energy_vs_edit"].items():
        print(k, v)


if __name__ == "__main__":
    main()
