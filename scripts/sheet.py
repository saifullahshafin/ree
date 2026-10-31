"""Contact sheet of stills at given timestamps, each tile labelled, for cheap visual verification.

  python sheet.py <video.mp4> <out.jpg> 1.5 6.8 13.2 ...   (or --events events.json --sample 12)
"""
import argparse, json, os, random, subprocess, tempfile
from PIL import Image, ImageDraw


def grab(video, t, path, width=480):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                    "-vf", f"scale={width}:-2", path], check=True)


def build(video, items, out, cols=4, width=480):
    tmp = tempfile.mkdtemp()
    tiles = []
    for i, (t, label) in enumerate(items):
        p = os.path.join(tmp, f"{i}.jpg")
        grab(video, t, p, width)
        im = Image.open(p).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 18], fill=(0, 0, 0))
        d.text((4, 3), f"#{i} {t:.1f}s {label}"[:78], fill=(255, 255, 0))
        tiles.append(im)
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (30, 30, 30))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(out, quality=82)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--events")
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--offset", type=float, default=0.8, help="Gemini floors timestamps; look slightly later")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.events:
        ev = json.load(open(a.events, encoding="utf-8"))
        ev = ev["events"] if isinstance(ev, dict) else ev
        random.seed(a.seed)
        by = {}
        for e in ev:
            by.setdefault(e["event_type"], []).append(e)
        pick = []
        while len(pick) < min(a.sample, len(ev)):
            for k in list(by):
                if by[k] and len(pick) < a.sample:
                    pick.append(by[k].pop(random.randrange(len(by[k]))))
        pick.sort(key=lambda e: e["t_start"])
        items = [(e["t_start"] + a.offset, f"{e['event_type']}/{e['graphic_kind']}") for e in pick]
        json.dump(pick, open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        items = [(t, "") for t in a.times]
    print(build(a.video, items, a.out))
