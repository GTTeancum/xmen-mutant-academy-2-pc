"""Check that every texture in a directory is something a person can recognise.

Two different questions get asked here, and they have different consequences.

**Is it decoded correctly?** A texture read at the wrong depth splits every byte into
two nibbles, which interleaves two unrelated images down alternating columns: one is a
coarse version of the picture, the other is noise. That is invisible in a thumbnail and
obvious in the statistics, so it is measured rather than eyeballed. A failure here means
the extraction is wrong and the image must not ship.

**Is it a picture?** Plenty of correctly decoded game art is a flat panel, a colour
ramp, or an effect mask, and none of those read as a picture however right they are.
That is not a defect, so those are flagged for a person to look at rather than rejected.

Usage:
    python tools/verify_textures.py --dir dump/tim/textures --out report
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

# A wrong-depth decode has to show up as BOTH: alternating columns that disagree, and
# one of the two column phases being far noisier than the other. Disagreement alone is
# not enough -- a name plate in a thin font disagrees just as much, because its strokes
# are one pixel wide, and rejecting those would throw away perfectly good art.
PHASE_LIMIT = 25.0
ROUGHNESS_LIMIT = 2.5


def _roughness(plane):
    """Mean absolute second difference: how far from smooth this image is."""
    if plane.shape[0] < 3 or plane.shape[1] < 3:
        return 0.0
    d = np.abs(2.0 * plane[1:-1, 1:-1] - plane[:-2, 1:-1] - plane[2:, 1:-1])         + np.abs(2.0 * plane[1:-1, 1:-1] - plane[1:-1, :-2] - plane[1:-1, 2:])
    return float(d.mean())


def phase_split(rgb):
    """(disagreement, roughness ratio) between the two column phases.

    Splitting an 8-bit index into two nibbles puts the high nibble -- a coarse but
    coherent picture -- in one phase and the low nibble -- effectively noise -- in the
    other. So the tell is not that the phases differ but that one is far rougher than
    the other. Real art keeps both phases about equally smooth.
    """
    if rgb.shape[1] < 8:
        return 0.0, 1.0
    even, odd = rgb[:, 0::2].astype(np.float64), rgb[:, 1::2].astype(np.float64)
    n = min(even.shape[1], odd.shape[1])
    even, odd = even[:, :n], odd[:, :n]
    disagree = float(np.abs(even - odd).mean())
    re, ro = _roughness(even.mean(axis=2)), _roughness(odd.mean(axis=2))
    ratio = max(re, ro) / max(min(re, ro), 1e-3)
    return disagree, float(ratio)


def classify(path):
    im = Image.open(path).convert('RGBA')
    a = np.asarray(im)
    rgb, alpha = a[..., :3], a[..., 3]
    visible = alpha > 0
    out = {
        'file': os.path.basename(path),
        'width': int(a.shape[1]),
        'height': int(a.shape[0]),
    }
    disagree, ratio = phase_split(rgb)
    out['phase'] = round(disagree, 2)
    out['roughness'] = round(ratio, 2)

    if not visible.any():
        out['verdict'] = 'flag'
        out['why'] = 'fully transparent'
        return out

    pixels = rgb[visible]
    colours = len(np.unique(pixels.reshape(-1, 3), axis=0))
    out['colours'] = int(colours)

    # A nibble split spreads indices across the whole palette, so it always lands on
    # plenty of colours. A handful of colours cannot be one however rough it looks.
    if colours > 8 and out['phase'] > PHASE_LIMIT and out['roughness'] > ROUGHNESS_LIMIT:
        out['verdict'] = 'reject'
        out['why'] = 'one column phase is far noisier than the other: wrong-depth decode'
        return out

    if colours <= 2:
        out['verdict'] = 'flag'
        out['why'] = 'flat fill' if colours == 1 else 'two colours'
        return out

    # A ramp is almost entirely explained by position along one axis; a picture is not.
    grey = rgb.mean(axis=2)
    h, w = grey.shape
    ys, xs = np.mgrid[0:h, 0:w]
    best = 0.0
    for coord in (xs, ys):
        c = coord[visible].astype(np.float64)
        g = grey[visible].astype(np.float64)
        if c.std() < 1e-6 or g.std() < 1e-6:
            continue
        best = max(best, abs(float(np.corrcoef(c, g)[0, 1])))
    out['ramp'] = round(best, 3)
    if best > 0.97:
        out['verdict'] = 'flag'
        out['why'] = 'colour ramp'
        return out

    out['verdict'] = 'pass'
    return out


def sheet(paths, out_path, cell=96, cols=14):
    if not paths:
        return
    rows = (len(paths) + cols - 1) // cols
    img = Image.new('RGB', (cols * cell, rows * cell), (28, 28, 32))
    for i, p in enumerate(paths):
        im = Image.open(p).convert('RGBA')
        bg = Image.new('RGBA', im.size, (255, 0, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert('RGB')
        s = min(cell / im.width, cell / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.NEAREST)
        img.paste(im, ((i % cols) * cell + (cell - im.width) // 2,
                       (i // cols) * cell + (cell - im.height) // 2))
    img.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sheets', type=int, default=280,
                    help='most images to put on each contact sheet')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    names = sorted(n for n in os.listdir(args.dir) if n.endswith('.png'))
    results = [classify(os.path.join(args.dir, n)) for n in names]

    groups = {}
    for r in results:
        groups.setdefault(r['verdict'], []).append(r)

    for verdict, rows in sorted(groups.items()):
        paths = [os.path.join(args.dir, r['file']) for r in rows[:args.sheets]]
        sheet(paths, os.path.join(args.out, f'{verdict}.png'))
        print(f'{verdict:7s} {len(rows):5d}')
        if verdict != 'pass':
            why = {}
            for r in rows:
                why[r['why']] = why.get(r['why'], 0) + 1
            for k, v in sorted(why.items(), key=lambda kv: -kv[1]):
                print(f'         {v:5d}  {k}')

    with open(os.path.join(args.out, 'report.json'), 'w') as fh:
        json.dump(results, fh, indent=1)
    print(f'report written to {args.out}')


main()
