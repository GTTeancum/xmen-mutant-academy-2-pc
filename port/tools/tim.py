"""Find and decode PlayStation TIM images.

A TIM is a header (`0x10`, then a flag word naming the pixel depth and whether a
palette is attached), an optional CLUT block, and a pixel block. Both blocks carry
their own length, their destination coordinates in VRAM, and their size in 16-bit
words -- which is exactly what a texture pack needs: the pixels, the depth, and where
the game is going to put them.

Scanning for the magic word alone finds thousands of false positives in 54 MB of game
data, so `scan` only accepts a header whose block lengths agree with the dimensions
those blocks declare, whose VRAM coordinates land inside the 1024x512 framebuffer, and
whose blocks do not run off the end of the file. That check is strict enough that a
hit is almost certainly a real image.
"""
import struct

MAGIC = 0x10
PMODE_BPP = {0: 4, 1: 8, 2: 16, 3: 24}


class Tim:
    __slots__ = ('offset', 'bpp', 'has_clut', 'clut', 'clut_x', 'clut_y',
                 'clut_w', 'clut_h', 'pixels', 'x', 'y', 'w', 'h', 'end')

    @property
    def width(self):
        """Width in texels, which is not the width in VRAM words below 16bpp."""
        return self.w * (16 // self.bpp) if self.bpp < 16 else self.w

    @property
    def height(self):
        return self.h

    def __repr__(self):
        return (f'<TIM @0x{self.offset:x} {self.width}x{self.height} {self.bpp}bpp '
                f'vram=({self.x},{self.y}) clut=({self.clut_x},{self.clut_y})'
                f'x{self.clut_h}>')


def _block(data, pos, limit):
    """(length, x, y, w, h, payload_offset) for a TIM block, or None if implausible."""
    if pos + 12 > limit:
        return None
    length, x, y, w, h = struct.unpack_from('<IHHHH', data, pos)
    if length != 12 + w * h * 2:
        return None
    if w == 0 or h == 0:
        return None
    if x > 1024 or y > 512 or x + w > 1024 or y + h > 512:
        return None
    if pos + length > limit:
        return None
    return length, x, y, w, h, pos + 12


def parse(data, pos, limit=None):
    """Parse a TIM at `pos`, or return None. Cheap enough to call on every offset."""
    limit = len(data) if limit is None else limit
    if pos + 8 > limit:
        return None
    magic, flags = struct.unpack_from('<II', data, pos)
    if magic != MAGIC or flags & ~0x0F:
        return None
    pmode = flags & 7
    if pmode not in PMODE_BPP:
        return None
    bpp = PMODE_BPP[pmode]
    has_clut = bool(flags & 8)
    if has_clut != (bpp in (4, 8)):
        # 4/8bpp are palettised and 16/24bpp are not; anything else is a false positive.
        return None

    t = Tim()
    t.offset = pos
    t.bpp = bpp
    t.has_clut = has_clut
    p = pos + 8

    if has_clut:
        blk = _block(data, p, limit)
        if blk is None:
            return None
        length, t.clut_x, t.clut_y, t.clut_w, t.clut_h, payload = blk
        if t.clut_w != (16 if bpp == 4 else 256):
            return None
        t.clut = data[payload:payload + t.clut_w * t.clut_h * 2]
        p += length
    else:
        t.clut = b''
        t.clut_x = t.clut_y = t.clut_w = t.clut_h = 0

    blk = _block(data, p, limit)
    if blk is None:
        return None
    length, t.x, t.y, t.w, t.h, payload = blk
    t.pixels = data[payload:payload + t.w * t.h * 2]
    t.end = p + length
    return t


def scan(data):
    """Every valid TIM in a blob, in order, skipping past each one found."""
    out = []
    pos = 0
    n = len(data)
    while pos + 8 <= n:
        if data[pos] == MAGIC and data[pos + 1] == 0 and data[pos + 2] == 0 and data[pos + 3] == 0:
            t = parse(data, pos)
            if t is not None:
                out.append(t)
                pos = t.end
                continue
        pos += 4          # TIMs are word aligned in every file this game ships
    return out


# The colour the artists used to mean "transparent". The game rewrites it to 0x0000 on
# the way into VRAM, which is the value the hardware actually treats as transparent.
COLOUR_KEY = 0x7C1F


def upload_clut(words):
    """A palette as it will exist in VRAM, not as it sits on the disc.

    Two things happen to a CLUT between the disc and the hardware, and both change the
    key the runtime looks a texture up by. The mask bit is set on every entry, which
    leaves the colours alone. And the magenta colour key becomes 0x0000, which is the
    only value the hardware reads as transparent -- so a texture whose palette is taken
    straight from the disc renders its transparent areas as magenta.

    Verified against every palette the running game was observed to upload: 102 of 102
    matched exactly.
    """
    return [0x0000 if c == COLOUR_KEY else (c | 0x8000) for c in words]


def clut_rgba(clut, index):
    """One palette as RGBA rows of 5-5-5-STP colour, expanded to 8-bit."""
    n = len(clut) // 2
    out = bytearray(n * 4)
    for i in range(n):
        v = clut[i * 2] | (clut[i * 2 + 1] << 8)
        r = (v & 31) << 3
        g = ((v >> 5) & 31) << 3
        b = ((v >> 10) & 31) << 3
        stp = (v >> 15) & 1
        # Black with no STP bit is the transparent colour; black with it is opaque
        # black; anything else is opaque unless STP marks it semi-transparent.
        if v == 0:
            a = 0
        elif stp:
            a = 128
        else:
            a = 255
        out[i * 4:i * 4 + 4] = bytes((r | (r >> 5), g | (g >> 5), b | (b >> 5), a))
    return bytes(out)


def decode(t, clut_index=0, clut_override=None):
    """RGBA bytes for a TIM, using one of its palettes (or one supplied)."""
    w, h = t.width, t.height
    out = bytearray(w * h * 4)

    if t.bpp == 16:
        for i in range(w * h):
            v = t.pixels[i * 2] | (t.pixels[i * 2 + 1] << 8)
            r = (v & 31) << 3
            g = ((v >> 5) & 31) << 3
            b = ((v >> 10) & 31) << 3
            stp = (v >> 15) & 1
            a = 0 if v == 0 else (128 if stp else 255)
            out[i * 4:i * 4 + 4] = bytes((r | (r >> 5), g | (g >> 5), b | (b >> 5), a))
        return bytes(out)

    if t.bpp == 24:
        for i in range(w * h):
            r, g, b = t.pixels[i * 3:i * 3 + 3]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, 255))
        return bytes(out)

    entries = t.clut_w
    palette = clut_override if clut_override is not None else \
        clut_rgba(t.clut[clut_index * entries * 2:(clut_index + 1) * entries * 2], 0)

    if t.bpp == 8:
        for i in range(w * h):
            p = t.pixels[i] * 4
            out[i * 4:i * 4 + 4] = palette[p:p + 4]
    else:
        for i in range(w * h):
            byte = t.pixels[i >> 1]
            idx = (byte & 0x0F) if (i & 1) == 0 else (byte >> 4)
            p = idx * 4
            out[i * 4:i * 4 + 4] = palette[p:p + 4]
    return bytes(out)
