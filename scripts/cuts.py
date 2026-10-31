"""Collapse ffmpeg scdet per-frame scores into discrete cut events (one peak per window)."""
import re, sys, json

def peaks(path, thresh=10.0, gap=0.5):
    txt = open(path, encoding='utf-8').read()
    rows = re.findall(r'pts_time:([\d.]+)\s+lavfi\.scd\.mafd=[\d.]+\s+lavfi\.scd\.score=([\d.]+)', txt)
    out = []
    for t, s in ((float(a), float(b)) for a, b in rows):
        if s < thresh:
            continue
        if out and t - out[-1]['t'] < gap:
            if s > out[-1]['score']:
                out[-1] = {'t': t, 'score': s}
            continue
        out.append({'t': t, 'score': s})
    return out

if __name__ == '__main__':
    p = peaks(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10.0)
    if len(sys.argv) > 3:
        json.dump(p, open(sys.argv[3], 'w'), indent=0)
    print(len(p), 'cuts')
