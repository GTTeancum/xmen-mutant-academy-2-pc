"""Combine textures read off the disc with textures observed at run time.

The disc is the better source: it gives every texture the game ships, framed exactly as
the artist saved it, whether or not a play session ever drew it. But it cannot explain
everything the game puts on screen -- some images are assembled in main memory before
being uploaded, and those exist only once the game is running.

Both sources name their files by the key the runtime looks textures up by, so merging
them is a matter of copying one over the other. The runtime dump wins on collisions: it
is what the game actually had in VRAM, so where the two disagree it is the one that
will match.

Usage:
    python tools/merge_textures.py --disc dump/tim/textures --dump dump/SLUS-01382/pages \\
                                   --out dump/merged/textures
"""
import argparse
import os
import shutil


def copy_pngs(src, dst):
    if not src or not os.path.isdir(src):
        return 0
    n = 0
    for name in sorted(os.listdir(src)):
        if not name.endswith('.png') or name.endswith('.idx.png'):
            continue
        shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--disc')
    ap.add_argument('--dump')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    from_disc = copy_pngs(args.disc, args.out)
    from_dump = copy_pngs(args.dump, args.out)
    total = len([n for n in os.listdir(args.out) if n.endswith('.png')])
    print(f'{from_disc} from the disc, {from_dump} from the run, '
          f'{total} distinct keys in {args.out}')


main()
