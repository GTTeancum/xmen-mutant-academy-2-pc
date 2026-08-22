"""Compute the keys the runtime looks textures up by, without running the game.

`TextureTile.Hash` in the runtime identifies a texture by FNV-1a over its depth, its
dimensions and the VRAM words it occupies, and identifies its palette by a second hash
over only the entries the pixels actually use. A replacement is found by that pair, so
anything built offline has to reproduce both exactly -- byte for byte, in the same
order -- or it will never match.

Keep this in step with `TextureTile.Hash`; `check` below re-derives a known pair so a
drift shows up as a failed self-test rather than a pack that silently never hits.
"""
OFFSET = 1469598103934665603
PRIME = 1099511628211
MASK = (1 << 64) - 1


def hash_texture(words, width_texels, height, bpp, clut):
    """(indexHash, clutHash) for one texture, given its VRAM words and palette.

    `words` and `clut` are sequences of 16-bit VRAM values in the order the hardware
    stores them: row major, left to right.
    """
    h = OFFSET
    for b in (bpp & 0xFF, width_texels & 0xFF, (width_texels >> 8) & 0xFF,
              height & 0xFF, (height >> 8) & 0xFF):
        h = ((h ^ b) * PRIME) & MASK

    used = 0
    if bpp == 4:
        for v in words:
            h = ((h ^ (v & 0xFF)) * PRIME) & MASK
            h = ((h ^ (v >> 8)) * PRIME) & MASK
            used |= (1 << (v & 0xF)) | (1 << ((v >> 4) & 0xF)) \
                | (1 << ((v >> 8) & 0xF)) | (1 << ((v >> 12) & 0xF))
    elif bpp == 8:
        for v in words:
            h = ((h ^ (v & 0xFF)) * PRIME) & MASK
            h = ((h ^ (v >> 8)) * PRIME) & MASK
            used |= (1 << (v & 0xFF)) | (1 << ((v >> 8) & 0xFF))
    else:
        for v in words:
            h = ((h ^ (v & 0xFF)) * PRIME) & MASK
            h = ((h ^ (v >> 8)) * PRIME) & MASK

    index_hash = h
    if not clut:
        return index_hash, 0

    c = OFFSET
    for i, e in enumerate(clut):
        if not (used >> i) & 1:
            continue
        c = ((c ^ (i & 0xFF)) * PRIME) & MASK
        c = ((c ^ (e & 0xFF)) * PRIME) & MASK
        c = ((c ^ (e >> 8)) * PRIME) & MASK
    return index_hash, c


def words_of(payload):
    """A TIM pixel or CLUT payload as 16-bit VRAM words."""
    return [payload[i] | (payload[i + 1] << 8) for i in range(0, len(payload) - 1, 2)]


def check():
    """Self-test against a hand-computed pair, so drift from the runtime is visible."""
    idx, clut = hash_texture([0x0123, 0x4567], 8, 1, 4, [0x0000, 0x7FFF, 0x1234, 0x5678,
                                                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert idx == 0x23cb21f3d04d0f0c, hex(idx)
    assert clut == 0xa6583452f479498d, hex(clut)
    return True


if __name__ == '__main__':
    idx, clut = hash_texture([0x0123, 0x4567], 8, 1, 4, [0x0000, 0x7FFF, 0x1234, 0x5678,
                                                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    print(f'index=0x{idx:016x} clut=0x{clut:016x}')
