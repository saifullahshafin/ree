"""Measured style fingerprint across a creator's videos (every number here is counted, not guessed).

  python stats.py --events <pack>/events --cuts <pack>/data --out <pack>/fingerprint.json
Prints a markdown summary; the JSON feeds the style bible.
"""
import argparse, glob, json, os, statistics as st
from collections import Counter, defaultdict

EDIT_SHOT_CHANGES = {"hard_cut", "jump_cut_same_shot", "layout_change", "camera_angle_change", "broll_insert",
                     "screenshot_insert", "chapter_card"}


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 2) if xs else None


def layout_timeline(events, dur):
    share, cur, t0 = Counter(), None, 0.0
    for e in events:
        if e["layout"] != cur:
            if cur:
                share[cur] += e["t_start"] - t0
            cur, t0 = e["layout"], e["t_start"]
    if cur:
        share[cur] += dur - t0
    return share


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--cuts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--include-unanchored", action="store_true")
    ap.add_argument("--transcripts", help="folder of word-timed transcripts, for pace and pause tightness")
    a = ap.parse_args()
    per_video, allev = {}, []
    layout_share, shot_lens, gaps = Counter(), [], []
    beat_graphic = defaultdict(Counter)
    energy_events = Counter()
    hook_rate, body_rate, total_dur, speech_all = [], [], 0.0, []
    for path in sorted(glob.glob(os.path.join(a.events, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        # unanchored events verified at about 1/3 accuracy: hints only, excluded from counts by default
        ev = [e for e in d["events"] if e["anchored"] or a.include_unanchored]
        dur = d["windows"][-1]["end"]
        total_dur += dur
        hard = json.load(open(os.path.join(a.cuts, f"{d['id']}_cuts.json")))
        sc = sorted(e["t_start"] for e in ev if e["event_type"] in EDIT_SHOT_CHANGES)
        shot_lens += [b - a_ for a_, b in zip(sc, sc[1:])]
        ts = sorted(e["t_start"] for e in ev)
        gaps += [b - a_ for a_, b in zip(ts, ts[1:])]
        layout_share.update(layout_timeline(ev, dur))
        for e in ev:
            beat_graphic[e["talk_beat"]][e["graphic_kind"]] += 1
            energy_events[e["speaker_energy"]] += 1
        hook = [e for e in ev if e["t_start"] < 60]
        hook_rate.append(len(hook))
        body_rate.append((len(ev) - len(hook)) / ((dur - 60) / 60))
        speech = {}
        if a.transcripts:
            w = json.load(open(os.path.join(a.transcripts, f"{d['id']}.json"), encoding="utf-8"))
            gaps_w = [b["start"] - x["end"] for x, b in zip(w, w[1:])]
            pauses = [g for g in gaps_w if g >= 0.25]       # audible pauses left in after the silence edit
            speech = {"wpm": round(len(w) / (dur / 60)), "pauses_per_min": round(len(pauses) / (dur / 60), 1),
                      "pause_median_s": q(pauses, .5), "pause_p90_s": q(pauses, .9), "pause_max_s": q(pauses, 1),
                      "pauses_over_1s": sum(g > 1 for g in pauses),
                      "fillers_per_min": round(sum(x["text"].lower().strip(".,?!") in ("uh", "um", "erm", "uhm")
                                                   for x in w) / (dur / 60), 1)}
            speech_all.append(speech)
        per_video[d["id"]] = {"duration_min": round(dur / 60, 1), "events": len(ev), "speech": speech,
                              "events_per_min": round(len(ev) / (dur / 60), 1),
                              "hard_cuts_per_min_meter": round(len(hard) / (dur / 60), 1),
                              "events_first_60s": len(hook),
                              "anchored_share": round(sum(e["anchored"] for e in d["events"]) / max(1, len(d["events"])), 2)}
        allev += ev
    c = lambda k: Counter(e[k] for e in allev).most_common()
    lag = [e["number_word_lag"] for e in allev if e["graphic_kind"] in
           ("number_counter", "bar_chart", "line_chart", "pie_or_donut", "table") and e["number_word_lag"] is not None]
    fp = {
        "videos": per_video,
        "total_minutes": round(total_dur / 60, 1),
        "events_total": len(allev),
        "shot_length_s": {"p25": q(shot_lens, .25), "median": q(shot_lens, .5), "p75": q(shot_lens, .75), "n": len(shot_lens)},
        "gap_between_any_edit_s": {"median": q(gaps, .5), "p90": q(gaps, .9), "max": q(gaps, 1)},
        "hook_events_first_60s_avg": round(st.mean(hook_rate), 1),
        "body_events_per_min_avg": round(st.mean(body_rate), 1),
        "layout_time_share": {k: round(v / total_dur, 3) for k, v in layout_share.most_common()},
        "event_type": c("event_type"), "graphic_kind": c("graphic_kind"), "dimension": c("dimension"),
        "motion_in": c("motion_in"), "motion_out": c("motion_out"), "audio_cue": c("audio_cue"),
        "talk_beat": c("talk_beat"), "speaker_energy": c("speaker_energy"),
        "beat_to_graphic": {b: g.most_common(5) for b, g in beat_graphic.items()},
        "data_graphic_lag_after_number_word_s": {"median": q(lag, .5), "p25": q(lag, .25), "p75": q(lag, .75), "n": len(lag)},
        "pop_with_sfx": sum(1 for e in allev if e["motion_in"] == "pop_scale" and e["audio_cue"].startswith("sfx")),
        "pop_total": sum(1 for e in allev if e["motion_in"] == "pop_scale"),
    }
    json.dump(fp, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: fp[k] for k in ("videos", "shot_length_s", "gap_between_any_edit_s", "hook_events_first_60s_avg",
                                          "body_events_per_min_avg", "layout_time_share")}, indent=1))


if __name__ == "__main__":
    main()
