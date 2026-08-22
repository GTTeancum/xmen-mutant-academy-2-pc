"""Decode every texture the game ships, straight from the disc.

This does not need the game to be running, and it does not care what a play session
happened to draw: it reads DATA/WAD.WAD, finds every TIM inside it, and writes one PNG
per texture along with a manifest recording the depth, the dimensions and the VRAM
coordinates the game will upload it to.

That last part is what makes the output usable as a replacement pack. The runtime looks
a texture up by hashing the VRAM it was uploaded into, and a TIM says exactly where it
goes, so the same key can be computed here as the game computes at draw time.

Usage:
    python tools/extract_textures.py --wad DISC/DATA/WAD.WAD --out dump/tim
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

import tim
import vramhash
from wad import Wad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wad', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    tex_dir = os.path.join(args.out, 'textures')
    os.makedirs(tex_dir, exist_ok=True)

    vramhash.check()
    wad = Wad(args.wad)
    manifest = []
    written = 0
    seen = set()

    for index in range(wad.count):
        blob = wad.entry(index)
        for slot, t in enumerate(tim.scan(blob)):
            w, h = t.width, t.height
            words = vramhash.words_of(t.pixels)
            shipped = vramhash.words_of(t.clut)

            # The palette in VRAM is not the palette on the disc: the mask bit is set
            # on every entry, and the magenta colour key becomes the hardware's real
            # transparent value. Both matter -- the first decides the key, the second
            # decides whether the sprite has transparency or a magenta blob.
            for palette in (tim.upload_clut(shipped),):
                index_hash, clut_hash = vramhash.hash_texture(words, w, h, t.bpp, palette)
                name = f'{index_hash:016x}_{clut_hash:016x}.png'
                if name in seen:
                    continue              # same pixels and palette: one key, one file
                seen.add(name)
                rgba = tim.decode(t, clut_override=tim.clut_rgba(
                    b''.join(bytes((c & 0xFF, c >> 8)) for c in palette), 0))
                arr = np.frombuffer(rgba, np.uint8).reshape(h, w, 4)
                Image.fromarray(arr, 'RGBA').save(os.path.join(tex_dir, name), optimize=True)
                manifest.append({
                    'file': name,
                    'indexHash': f'{index_hash:016x}',
                    'clutHash': f'{clut_hash:016x}',
                    'wad': index,
                    'slot': slot,
                    'offset': t.offset,
                    'bpp': t.bpp,
                    'width': w,
                    'height': h,
                    'vramX': t.x,
                    'vramY': t.y,
                    'vramW': t.w,
                    'clutX': t.clut_x,
                    'clutY': t.clut_y,
                    'clutCount': t.clut_w,
                })
                written += 1

    with open(os.path.join(args.out, 'textures.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    print(f'{written} textures written to {tex_dir}')


main()
