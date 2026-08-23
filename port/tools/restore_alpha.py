"""Put correct transparency back onto a texture upscaled somewhere else.

Web upscalers flatten alpha: they either drop it, or interpolate it into a gradient.
Neither survives here. A PS1 texel is transparent, semi-transparent (the STP bit) or
opaque, and the shader reads that back at exactly 0 / 128 / 255 -- a value in between
changes which of the three a pixel means, so a smooth alpha edge is not a soft edge, it
is a row of pixels that mean the wrong thing.

So the alpha is not upscaled from the file you bring back. It is rebuilt from the
original texture, by scaling one mask per state and taking the strongest per pixel:
edges land on the 4x grid without a fourth value ever being invented. Only the colour
comes from your upscale.

Usage:
    python tools/restore_alpha.py --original assets/pack-source \\
                                  --upscaled my-edits --out packs/xmenma2-4x/textures

`--upscaled` may be a single file or a directory; names must match the originals.
"""
import argparse
import os

import numpy as np
from PIL import Image


def upscale_alpha(alpha, scale):
    """4x the alpha channel while keeping it to the three values the shader knows."""
    h, w = alpha.shape
    size = (w * scale, h * scale)
    states = [v for v in (0, 128, 255) if (alpha == v).any()]
    leftover = ~np.isin(alpha, [0, 128, 255])
    if leftover.any():
        states = sorted(set(states) | {255})
    if len(states) == 1:
        return np.full((size[1], size[0]), states[0], np.uint8)

    best = winner = None
    for v in states:
        mask = ((alpha == v).astype(np.float32) * 255).astype(np.uint8)
        up = np.asarray(Image.fromarray(mask).resize(size, Image.BILINEAR), np.float32)
        if best is None:
            best, winner = up, np.full(up.shape, v, np.uint8)
        else:
            take = up > best
            best = np.where(take, up, best)
            winner = np.where(take, np.uint8(v), winner)
    return winner


def restore(original_path, upscaled_path, out_path):
    orig = Image.open(original_path)
    if orig.mode != 'RGBA':
        orig = orig.convert('RGBA')
    a = np.asarray(orig)
    alpha = a[..., 3]

    up = Image.open(upscaled_path).convert('RGB')
    if up.width % orig.width or up.height % orig.height:
        return f'{os.path.basename(upscaled_path)}: {up.width}x{up.height} is not a whole ' \
               f'multiple of {orig.width}x{orig.height}'
    sx, sy = up.width // orig.width, up.height // orig.height
    if sx != sy:
        return f'{os.path.basename(upscaled_path)}: scaled {sx}x horizontally but {sy}x vertically'

    rgb = np.asarray(up)
    up_a = upscale_alpha(alpha, sx)
    h = min(rgb.shape[0], up_a.shape[0])
    w = min(rgb.shape[1], up_a.shape[1])
    out = np.dstack([rgb[:h, :w], up_a[:h, :w]])
    Image.fromarray(out, 'RGBA').save(out_path, optimize=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--original', required=True,
                    help='the texture, or a directory of them, at original size')
    ap.add_argument('--upscaled', required=True, help='a file or a directory')
    ap.add_argument('--out', required=True, help='output directory')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    if os.path.isfile(args.upscaled):
        names = [os.path.basename(args.upscaled)]
        up_dir = os.path.dirname(os.path.abspath(args.upscaled))
    else:
        names = sorted(n for n in os.listdir(args.upscaled) if n.lower().endswith('.png'))
        up_dir = args.upscaled

    orig_dir = args.original if os.path.isdir(args.original) else os.path.dirname(args.original)

    done = 0
    for name in names:
        orig = os.path.join(orig_dir, name)
        if not os.path.exists(orig):
            print(f'  no original for {name} -- names must match')
            continue
        err = restore(orig, os.path.join(up_dir, name), os.path.join(args.out, name))
        if err:
            print('  ' + err)
        else:
            done += 1
    print(f'{done} texture(s) written to {args.out}')


main()
