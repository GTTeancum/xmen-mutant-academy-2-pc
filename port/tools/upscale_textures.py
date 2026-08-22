"""
Builds a 4x Real-ESRGAN texture pack from a RecompOne texture dump.

Run the game with XMENMA2_DUMP=all to collect `dump/<GAME>/textures` (the exact tiles
the game samples) and `dump/<GAME>/pages` (whole 256-texel texture pages). Then point
this at the dump; it writes `packs/<id>/` which the runtime picks up automatically.
Anything without a replacement keeps using the original VRAM texture, so a partial
pack is always safe.

Four details make or break the result:

**Alpha is a flag, not a gradient.** A PS1 texel is transparent (colour 0x0000),
semi-transparent (the STP bit), or opaque, and the runtime's shader reads that back at
exactly 0 / 128 / 255 -- anything in between changes which of the three a pixel means.
So ESRGAN never sees the alpha channel. It upscales RGB only, and the alpha is rebuilt
by upscaling one mask per state and taking the winner per pixel, which keeps the three
values exact while still giving a 4x-resolution silhouette.

**Transparent pixels are black.** Feeding that to the network drags dark halos in
around every sprite edge, so transparent areas are flood-filled with the nearest
opaque colour first. The fill is thrown away afterwards -- it only exists so the
network has something sensible to blend towards.

**The art is dithered, and dither does not survive magnification.** A 16-entry palette
cannot hold a gradient, so the artists alternated two entries every other pixel to fake
the shades in between. Enlarged, that stops reading as shading and starts reading as
grain -- and an upscaling network reads it as structure and redraws it as swirls. The
fix is not to use less of the network. It is to cancel the dither before the network
ever sees it, so the network spends its capacity enlarging art instead of fighting
noise. See `dedither`.

**The network will drift the colour if you let it.** Even on clean input an
illustration-trained model shifts hue and flattens shading; on this game's palettes it
drifts far enough to look like a different scene. So the network's output is only used
for its high frequencies -- edges, de-blocking -- while every large-scale value comes
from the original. See `detail_transfer`. That combination measures out roughly ten
times less colour drift than the raw network and holds detail the old strength blend
threw away.

Usage:
    python tools/upscale_textures.py --dump bin/Release/net10.0/dump/SLUS-01382 \\
                                     --out  bin/Release/net10.0/packs/xmenma2-esrgan-4x
Options:
    --model NAME    realesrgan-x4plus-anime (default) | realesr-animevideov3 |
                    realesrgan-x4plus
    --tile N        ESRGAN tile size; lower it if Vulkan runs out of memory (default 32).
                    realesrgan-x4plus does not fit on a shared-memory iGPU at any size,
                    and this build has no CPU fallback, so both usable models are
                    anime-trained -- which is what the de-dither and the detail
                    transfer are for.
    --detail SIGMA  radius, in output pixels, of the split between "the original's
                    colour" and "the network's detail" (default 4, one source texel).
                    0 disables it and writes the raw network output.
    --no-dedither   feed the network the dithered original. Only useful for comparing.
    --strength F    legacy dial: mix the result back towards a plain resample, 0..1
                    (default 1.0 = off). This trades the network's redrawing for the
                    source's own grain and cannot land anywhere good, because the grain
                    is the thing that looks wrong when magnified. Kept only so old
                    packs can be reproduced.
    --batch N       images per ESRGAN invocation (default 2000)
    --only tiles|pages|both
    --force         re-upscale images already present in the output pack

Don't run this while the game is running. Both want the GPU, and on a shared-memory
iGPU the heavier models fail to allocate when something else already holds VRAM --
that is what an otherwise unexplained "vkAllocateMemory failed" means.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from scipy.ndimage import (uniform_filter, gaussian_filter,
                           minimum_filter, maximum_filter)

SCALE = 4
ESRGAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', 'tools', 'esrgan', 'realesrgan-ncnn-vulkan.exe')

# waifu2x-caffe, which is old, CPU-only on this machine, and the right tool anyway.
# Real-ESRGAN's usable models here are all anime-trained, and on this game's art they do
# not enlarge so much as redraw: smooth gradient shading comes back as flat regions
# separated by hard dark contours the original never had. That is most obvious on the
# character-select portraits, where it reads as blobs. waifu2x interpolates and denoises
# rather than restyling, so the shading survives. Its photo and upresnet10 models are
# the ones to use; the anime models here have the same problem Real-ESRGAN does.
WAIFU2X = r'C:\Games\zzModTools\waifu2x-caffe\waifu2x-caffe-cui.exe'

# Dither detection. LO/HI ramp the mask in over the measured amplitude of the
# alternating pattern, in 0..255 levels. OPEN is the width the pattern has to cover
# before it counts as dither at all, and DEAD is the mask value below which a pixel is
# passed through untouched rather than slightly blurred.
DITHER_LO, DITHER_HI = 2.0, 6.0
DITHER_WIN = 4
DITHER_OPEN = 13
DITHER_DEAD = 0.15


def bleed(rgb, opaque, rounds=8):
    """Grow the opaque colours outward into transparent pixels.

    Transparent texels carry no colour of their own (they decode to black), and a
    network blending towards black leaves a dark fringe on every sprite edge. Repeated
    4-neighbour dilation gives those pixels a plausible colour instead. Only the
    visible pixels survive into the final image; this is purely to steer the upscale.
    """
    out = rgb.astype(np.float32).copy()
    known = opaque.copy()
    for _ in range(rounds):
        if known.all():
            break
        acc = np.zeros_like(out)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(out, dy, 0), dx, 1)
            sk = np.roll(np.roll(known, dy, 0), dx, 1).astype(np.float32)
            if dy == 1:   sk[0, :] = 0
            if dy == -1:  sk[-1, :] = 0
            if dx == 1:   sk[:, 0] = 0
            if dx == -1:  sk[:, -1] = 0
            acc += sh * sk[..., None]
            cnt += sk
        fill = (~known) & (cnt > 0)
        if not fill.any():
            break
        out[fill] = acc[fill] / cnt[fill][..., None]
        known |= fill
    return np.clip(out, 0, 255).astype(np.uint8)


def _k121(x, axis):
    """[1,2,1]/4 along one axis, edge-replicated.

    This kernel has an exact zero at the Nyquist frequency, which is where a
    one-pixel-period dither lives: two alternating colours both come out as their
    average, and nothing else in the image moves nearly as far.
    """
    a = np.roll(x, 1, axis)
    b = np.roll(x, -1, axis)
    lo = [slice(None)] * x.ndim
    hi = [slice(None)] * x.ndim
    lo[axis] = 0
    hi[axis] = -1
    a[tuple(lo)] = x[tuple(lo)]
    b[tuple(hi)] = x[tuple(hi)]
    return (a + 2.0 * x + b) * 0.25


def _amp(img, sign, win):
    """Local amplitude of the component that alternates with `sign`.

    Multiplying by the alternating sign turns that one pattern into a DC offset, and an
    even-sized box mean then cancels everything that does not alternate the same way.
    What survives is the strength of that exact pattern rather than local contrast in
    general, so edges and fine detail read near zero here while dither reads large.
    """
    s = uniform_filter(img * sign[..., None], size=(win, win, 1), mode='nearest')
    return np.abs(s).max(axis=2)


def _ramp(a, lo, hi):
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def _open(mask, size):
    """Keep only pattern that covers an area; drop small patches.

    Dithering is a field: it runs across a whole shaded region. Pixel art also uses
    alternating rows deliberately -- the counters of a letter, a one-pixel highlight --
    and those look identical to a detector that only ever sees a few pixels at once.
    Requiring the pattern to survive an erosion this wide is what separates them: a
    dithered flank keeps its mask, two dark rows inside a glyph lose theirs.
    """
    if size <= 1:
        return mask
    return maximum_filter(minimum_filter(mask, size, mode='nearest'), size, mode='nearest')


def dedither(rgb):
    """Cancel ordered dithering, and leave everything else exactly as it was.

    Each of the three patterns a palette artist actually uses -- vertical stripes,
    horizontal stripes, checkerboard -- is measured separately and cancelled only along
    the axes it alternates on, so a vertically dithered area keeps its horizontal
    detail. Areas that are not dithered come through bit-identical, which matters more
    than it sounds: the fonts and UI art in this game are hard-edged pixel work, and
    the network is unstable enough on them that even a few levels of stray blur is the
    difference between clean glyphs and invented marks inside them.
    """
    f = rgb.astype(np.float32)
    h, w = f.shape[:2]
    yy, xx = np.indices((h, w))
    sx = np.where(xx % 2 == 0, 1.0, -1.0).astype(np.float32)
    sy = np.where(yy % 2 == 0, 1.0, -1.0).astype(np.float32)

    ax = _amp(f, sx, DITHER_WIN)
    ay = _amp(f, sy, DITHER_WIN)
    axy = _amp(f, sx * sy, DITHER_WIN)

    # A checkerboard alternates on both axes, so it drives both masks; a stripe drives
    # only the one it runs against.
    mx = _open(_ramp(np.maximum(ax, axy), DITHER_LO, DITHER_HI), DITHER_OPEN)
    my = _open(_ramp(np.maximum(ay, axy), DITHER_LO, DITHER_HI), DITHER_OPEN)
    # Softening the mask keeps filtered and unfiltered areas from meeting at a visible
    # seam; the dead zone then puts the tail of that softening back to exactly zero, so
    # a pixel is either dithered and filtered or art and untouched.
    mx = _ramp(gaussian_filter(mx, 1.5, mode='nearest'), DITHER_DEAD, 1.0)[..., None]
    my = _ramp(gaussian_filter(my, 1.5, mode='nearest'), DITHER_DEAD, 1.0)[..., None]

    out = f + mx * (_k121(f, 1) - f)
    out = out + my * (_k121(out, 0) - out)
    return np.clip(out, 0, 255).astype(np.uint8)


def detail_transfer(esrgan, base, sigma):
    """Keep the network's edges, keep the original's colour.

    Everything below `sigma` -- the sharpened edges, the de-blocking, the reason for
    running a network at all -- comes from the network. Everything above it -- local
    mean colour, shading, palette -- comes from the original, plainly resampled. The
    result cannot drift in hue or brightness the way a raw network output does, because
    every large-scale value in it is the game's own, and unlike mixing the two whole
    images it gives up no sharpness to get that.
    """
    e = esrgan.astype(np.float32)
    b = base.astype(np.float32)
    lo_e = gaussian_filter(e, (sigma, sigma, 0), mode='nearest')
    lo_b = gaussian_filter(b, (sigma, sigma, 0), mode='nearest')
    return np.clip(lo_b + (e - lo_e), 0, 255)


def upscale_alpha(alpha):
    """4x the alpha channel while keeping it to the three values the shader knows.

    One mask per state is scaled smoothly and the strongest wins, so edges land on a
    4x grid instead of a 1x one without ever inventing a fourth alpha value.
    """
    h, w = alpha.shape
    size = (w * SCALE, h * SCALE)
    states = [v for v in (0, 128, 255) if (alpha == v).any()]
    leftover = ~np.isin(alpha, [0, 128, 255])
    if leftover.any():                      # shouldn't happen, but never guess
        states = sorted(set(states) | {255})
    if len(states) == 1:
        return np.full((size[1], size[0]), states[0], np.uint8)

    best = None
    winner = None
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


def prepare(src, work, do_dedither):
    """Write the bleed-filled, de-dithered, alpha-free copy ESRGAN will actually see.

    Returns the original alpha and a digest of what the network will be given, so
    identical inputs can share one upscale.
    """
    im = Image.open(src)
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    a = np.asarray(im)
    rgb, alpha = a[..., :3], a[..., 3]
    opaque = alpha > 0
    if not opaque.any():
        return None, None                    # fully transparent: nothing to upscale
    # Bleed first: the fill has no dither of its own, so de-dithering afterwards never
    # sees a false pattern at the sprite edges.
    filled = bleed(rgb, opaque)
    prepared = dedither(filled) if do_dedither else filled
    Image.fromarray(prepared, 'RGB').save(work)
    return alpha, hashlib.blake2b(prepared.tobytes(), digest_size=16).hexdigest()


def finish(up_path, work_path, alpha, dst, detail, strength):
    """Recombine the upscaled colour with the rebuilt alpha."""
    rgb = np.asarray(Image.open(up_path).convert('RGB')).astype(np.float32)

    if detail > 0 or strength < 0.999:
        base = np.asarray(Image.open(work_path).convert('RGB').resize(
            (rgb.shape[1], rgb.shape[0]), Image.LANCZOS), np.float32)
        if detail > 0:
            rgb = detail_transfer(rgb, base, detail)
        if strength < 0.999:
            rgb = base * (1.0 - strength) + rgb * strength

    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    up_a = upscale_alpha(alpha)
    h = min(rgb.shape[0], up_a.shape[0])
    w = min(rgb.shape[1], up_a.shape[1])
    out = np.dstack([rgb[:h, :w], up_a[:h, :w]])
    Image.fromarray(out, 'RGBA').save(dst, optimize=True)


def run_waifu2x(indir, outdir, model, noise):
    exe = os.path.abspath(WAIFU2X)
    root = os.path.dirname(exe)
    cmd = [exe, '-i', os.path.abspath(indir), '-o', os.path.abspath(outdir),
           '-m', 'noise_scale', '-n', str(noise), '-s', str(SCALE), '-p', 'cpu',
           '--model_dir', os.path.join(root, 'models', model), '-e', 'png']
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
    produced = len(os.listdir(outdir)) if os.path.isdir(outdir) else 0
    if produced == 0:
        tail = (p.stderr or p.stdout or '').strip().splitlines()[-3:]
        raise RuntimeError('waifu2x produced nothing: ' + ' | '.join(tail))


def run_esrgan(indir, outdir, model, tile):
    # Absolute: this runs with cwd set to the esrgan folder so it finds `models/`,
    # and a relative path would resolve against that instead of the caller's directory.
    cmd = [os.path.abspath(ESRGAN), '-i', os.path.abspath(indir), '-o', os.path.abspath(outdir),
           '-s', str(SCALE), '-t', str(tile), '-n', model, '-f', 'png']
    p = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.abspath(ESRGAN)))
    if p.returncode != 0 or 'failed' in (p.stderr or '').lower():
        tail = (p.stderr or p.stdout or '').strip().splitlines()[-3:]
        raise RuntimeError('realesrgan failed: ' + ' | '.join(tail))


def gather(dump, only):
    groups = []
    if only in ('tiles', 'both'):
        groups.append(('textures', os.path.join(dump, 'textures')))
    if only in ('pages', 'both'):
        groups.append(('pages', os.path.join(dump, 'pages')))
    files = []
    for kind, d in groups:
        if not os.path.isdir(d):
            print(f'  (no {kind} directory at {d})')
            continue
        for n in sorted(os.listdir(d)):
            # .idx.png is an index-map visualisation, not colour; cluts are palettes.
            # Neither survives interpolation, and neither is what gets sampled.
            if not n.endswith('.png') or n.endswith('.idx.png'):
                continue
            files.append((kind, os.path.join(d, n), n))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--model', default='realesrgan-x4plus-anime')
    ap.add_argument('--tile', type=int, default=32)
    ap.add_argument('--batch', type=int, default=2000)
    ap.add_argument('--only', default='both', choices=('tiles', 'pages', 'both'))
    ap.add_argument('--detail', type=float, default=4.0,
                    help='split radius in output pixels between the original\'s colour '
                         'and the network\'s detail (default 4); 0 writes the raw network')
    ap.add_argument('--no-dedither', dest='dedither', action='store_false',
                    help='feed the network the dithered original (for comparison only)')
    ap.add_argument('--strength', type=float, default=1.0,
                    help='legacy: mix the result back towards a plain resample, 0..1')
    ap.add_argument('--engine', default='waifu2x', choices=('waifu2x', 'esrgan'),
                    help='which upscaler to use (default waifu2x: it does not restyle)')
    ap.add_argument('--w2x-model', dest='w2x_model', default='upresnet10',
                    help='waifu2x model directory name (upresnet10, upconv_7_photo, cunet)')
    ap.add_argument('--noise', type=int, default=1, choices=(0, 1, 2, 3),
                    help='waifu2x denoise level (default 1)')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(ESRGAN):
        sys.exit(f'realesrgan-ncnn-vulkan not found at {os.path.abspath(ESRGAN)}')

    tex_out = os.path.join(args.out, 'textures')
    os.makedirs(tex_out, exist_ok=True)

    files = gather(args.dump, args.only)
    if not args.force:
        have = set(os.listdir(tex_out))
        files = [f for f in files if f[2] not in have]
    recipe = describe(args)
    engine = f'waifu2x/{args.w2x_model} n{args.noise}' if args.engine == 'waifu2x' else args.model
    print(f'{len(files)} image(s) to upscale with {engine} at {SCALE}x, {recipe}')
    if not files:
        write_manifest(args.out, engine, len(os.listdir(tex_out)), recipe)
        return

    work = os.path.join(args.out, '.work')
    started = time.time()
    done = skipped = 0

    for base in range(0, len(files), args.batch):
        chunk = files[base:base + args.batch]
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(os.path.join(work, 'in'))
        os.makedirs(os.path.join(work, 'out'))

        alphas = {}
        # Two entries that differ only in palette transparency have identical colour,
        # and the network only ever sees colour. Upscaling one and reusing it for the
        # others is exact, not an approximation, and halves the work on a pack that
        # carries both palette forms of every texture.
        twins = {}
        for _kind, src, name in chunk:
            try:
                a, digest = prepare(src, os.path.join(work, 'in', name), args.dedither)
            except Exception as e:
                print(f'  skip {name}: {e}')
                a = None
            if a is None:
                skipped += 1
                continue
            alphas[name] = a
            first = twins.setdefault(digest, name)
            if first != name:
                os.remove(os.path.join(work, 'in', name))
                twins[name] = first

        if alphas:
            if args.engine == 'waifu2x':
                run_waifu2x(os.path.join(work, 'in'), os.path.join(work, 'out'),
                            args.w2x_model, args.noise)
            else:
                run_esrgan(os.path.join(work, 'in'), os.path.join(work, 'out'),
                           args.model, args.tile)
            for name, alpha in alphas.items():
                source = twins.get(name, name)
                up = os.path.join(work, 'out', source)
                if not os.path.exists(up):
                    skipped += 1
                    continue
                finish(up, os.path.join(work, 'in', source), alpha,
                       os.path.join(tex_out, name), args.detail, args.strength)
                done += 1

        rate = done / max(time.time() - started, 1e-3)
        print(f'  {done}/{len(files)} done, {skipped} skipped, {rate:.1f}/s')

    shutil.rmtree(work, ignore_errors=True)
    write_manifest(args.out, engine, len(os.listdir(tex_out)), recipe)
    print(f'pack written to {args.out}: {len(os.listdir(tex_out))} textures')


def describe(args):
    """One phrase naming what this pack actually did, for the manifest and the log."""
    bits = []
    bits.append('de-dithered' if args.dedither else 'dither kept')
    bits.append(f'detail transfer r{args.detail:g}' if args.detail > 0 else 'raw network')
    if args.strength < 0.999:
        bits.append(f'strength {args.strength:g}')
    return ', '.join(bits)


def write_manifest(out, model, count, recipe):
    manifest = {
        "formatVersion": 1,
        "id": "xmenma2-esrgan-4x",
        "name": "X-Men: Mutant Academy 2 — 4x ESRGAN textures",
        "version": "1.0",
        "description": f"Game textures upscaled 4x with Real-ESRGAN ({model}, {recipe}). "
                       f"Anything not present falls back to the original. "
                       f"{count} textures.",
        "priority": 10,
        "game": {"id": "SLUS-01382", "strict": True},
    }
    with open(os.path.join(out, 'pack.json'), 'w') as fh:
        json.dump(manifest, fh, indent=2)


main()
