#!/usr/bin/env python3
"""Does the widened frame stop at the 4:3 edge?

The question this answers: when a widescreen capture has black at the sides, is the
renderer refusing to draw past the console's own frame, or has the arena simply run
out of scenery there?

A renderer that clipped would leave the picture bright right up to the 4:3 edge and
exactly nothing beyond it, in every frame. Scenery running out is gradual, follows the
geometry rather than the frame, and is as likely to be dark just inside the edge as
just outside. So: compare the mean brightness of the ten columns inside each edge
against the ten columns outside it.

    -100%  nothing at all outside      a hard cut, and for a 2D screen that is correct
    < -60% consistently, every frame   a clip worth investigating
    scattered, sometimes positive      the arena, not the renderer

Usage: python tools/wide_check.py <directory of captures> [more directories]
"""
import sys, os, glob
import numpy as np
from PIL import Image


def rows(path):
    for f in sorted(glob.glob(os.path.join(path, "frame_*.png"))):
        im = np.asarray(Image.open(f).convert("L")).astype(float)
        h4, w4 = im.shape
        if w4 % 4 or h4 % 4:
            continue                      # not a 4x internal-resolution capture
        w, h = w4 // 4, h4 // 4
        if w <= 512:
            continue                      # 4:3, nothing to check
        m = (w - 512) // 2
        col = im.reshape(h, 4, w, 4).mean(axis=(1, 3)).mean(axis=0)
        yield (os.path.basename(f),
               col[m:m + 10].mean(), col[max(0, m - 10):m].mean(),
               col[w - m - 10:w - m].mean(), col[w - m:w - m + 10].mean())


def main(paths):
    print(f"{'frame':>18} {'in L':>6} {'out L':>6} {'step':>6}   {'in R':>6} {'out R':>6} {'step':>6}")
    steps = []
    for p in paths:
        print(f"\n{p}")
        for name, il, ol, ir, orr in rows(p):
            dl = (ol - il) / il * 100 if il > 0.5 else float("nan")
            dr = (orr - ir) / ir * 100 if ir > 0.5 else float("nan")
            steps += [d for d in (dl, dr) if d == d]
            print(f"{name:>18} {il:6.1f} {ol:6.1f} {dl:5.0f}%   {ir:6.1f} {orr:6.1f} {dr:5.0f}%")
    if not steps:
        print("\nno widened captures found")
        return
    hard = sum(1 for d in steps if d < -95)
    print(f"\n{len(steps)} edges measured, {hard} of them cut to nothing "
          f"({hard / len(steps):.0%}), median step {np.median(steps):.0f}%")
    print("a 2D screen cuts to nothing and should; gameplay should not")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
