"""Visual report of a style pack: one self-contained HTML page where the data speaks (charts first, little text).

Reads whatever the pack has (events, fingerprint, patterns, look, specs, sound, verification, run stats);
missing layers render as 'pending'. Re-run after every stage.

  python report.py --pack <pack> --creator "Ali Abdaal" --out <pack>/report.html
"""
import argparse, glob, json, os

GROUPS = {
    "pip_over_graphic": "PIP over graphic", "talking_head_medium": "Face medium", "talking_head_wide": "Face wide",
    "talking_head_close": "Face close / punch-in", "talking_head_punch_in": "Face close / punch-in",
    "fullscreen_graphic": "Full-screen graphic", "title_card": "Full-screen graphic", "chapter_card": "Full-screen graphic",
}
GROUP_ORDER = ["PIP over graphic", "Face medium", "Face wide", "Face close / punch-in", "Full-screen graphic", "B-roll & screen"]


def grp(layout):
    return GROUPS.get(layout, "B-roll & screen")


def load(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build(pack, creator):
    D = {"creator": creator, "groups": GROUP_ORDER}
    D["run"] = load(os.path.join(pack, "run.json"), {})
    vids, timelines = [], []
    sfx_ev = {os.path.basename(p)[:-5]: load(p) for p in glob.glob(os.path.join(pack, "sound", "sfx_ev", "*.json"))}
    sound = {os.path.basename(p)[:-5]: load(p) for p in glob.glob(os.path.join(pack, "sound", "mix", "*.json"))}
    for p in sorted(glob.glob(os.path.join(pack, "events", "*.json"))):
        d = load(p)
        info = load(next(iter(glob.glob(os.path.join(pack, "source", d["id"] + "_*.info.json"))), ""), {}) or {}
        dur = d["windows"][-1]["end"]
        ev = [e for e in d["events"] if e["anchored"]]
        bands, cur, t0 = [], None, 0.0
        for e in ev:
            g = grp(e["layout"])
            if g != cur:
                if cur:
                    bands.append([round(t0, 2), round(e["t_start"], 2), GROUP_ORDER.index(cur)])
                cur, t0 = g, e["t_start"]
        if cur:
            bands.append([round(t0, 2), round(dur, 2), GROUP_ORDER.index(cur)])
        gfx = [[round(e["t_start"], 2), e["graphic_kind"], (e["onscreen_text"] or e["event_type"])[:60]]
               for e in ev if e["graphic_kind"] not in ("none", "self_shot_broll", "stock_footage")]
        sx = sfx_ev.get(d["id"])
        sfx = [[r["t"], r["gemini_audio"].replace("sfx_", "")] for r in sx["events"] if r["sfx_measured"]] if sx else []
        snd = sound.get(d["id"])
        music = [[m["start"], m["end"]] for m in snd["music_segments"]] if snd else []
        title = info.get("title", d["id"])
        vids.append({"id": d["id"], "title": title, "min": round(dur / 60, 1)})
        timelines.append({"id": d["id"], "title": title, "dur": dur, "bands": bands, "gfx": gfx, "sfx": sfx, "music": music})
    D["videos"], D["timelines"] = vids, timelines
    D["fp"] = load(os.path.join(pack, "fingerprint.json"))
    D["pat"] = load(os.path.join(pack, "patterns.json"))
    D["look"] = load(os.path.join(pack, "look.json"))
    D["verify"] = load(os.path.join(pack, "verify", "verify.json"))
    specs = []
    for p in sorted(glob.glob(os.path.join(pack, "specs", "*.json"))):
        s = load(p)
        if s:
            specs.append({"kind": s["source_event"]["graphic_kind"], "entrance": s["entrance"][:140],
                          "type": s["typography"][:120], "pos": s["position"][:90],
                          "pal": [c for c in s["palette_measured"] if c["share"] >= 0.03][:5]})
    D["specs"] = specs
    if sx_all := [v for v in sfx_ev.values() if v]:
        lab = {}
        for v in sx_all:
            for k, b in v["by_gemini_label"].items():
                L = lab.setdefault(k, {"n": 0, "hit": 0.0, "rise": []})
                L["n"] += b["n"]; L["hit"] += b["share_over_control_p90"] * b["n"]; L["rise"].append(b["median_rise_db"])
        D["sfx_check"] = {k: {"n": v["n"], "share": round(v["hit"] / v["n"], 2), "rise": round(sum(v["rise"]) / len(v["rise"]), 1)}
                          for k, v in lab.items()}
        D["sfx_control"] = round(sum(v["control_rise_db"]["p90"] for v in sx_all) / len(sx_all), 1)
        offs = [r["peak_offset_ms"] for v in sx_all for r in v["events"] if r["sfx_measured"] and r["gemini_audio"].startswith("sfx")]
        D["sfx_offsets"] = offs
    D["mix"] = {k: {"lufs": v["integrated_lufs"], "lra": v["loudness_range_lu"], "music": v["music_share"],
                    "duck": sorted(m["duck_db"] for m in v["music_segments"] if m["duck_db"] is not None)[len([m for m in v["music_segments"] if m["duck_db"] is not None]) // 2]
                    if any(m["duck_db"] is not None for m in v["music_segments"]) else None,
                    "bpm": [m["tempo_bpm"] for m in v["music_segments"] if m["tempo_bpm"]]}
                for k, v in sound.items() if v}
    return D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--creator", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    D = build(a.pack, a.creator)
    tpl = open(os.path.join(os.path.dirname(__file__), "..", "assets", "report_template.html"), encoding="utf-8").read()
    html = tpl.replace("__CREATOR__", a.creator).replace("/*__DATA__*/null", json.dumps(D, ensure_ascii=False))
    open(a.out, "w", encoding="utf-8").write(html)
    print(a.out, round(len(html) / 1024), "KB")


if __name__ == "__main__":
    main()
