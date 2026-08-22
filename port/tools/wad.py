"""Read DATA/WAD.WAD, the game's asset archive.

The header is `PWF `, the archive length, a version, and an entry count; the table of
contents follows at 0x800 as a flat array of 32-bit (offset, size) pairs, every offset
aligned to a 2048-byte sector. There are no names -- an entry is identified by its
index, which is what the game's code indexes it by.

Usage:
    python tools/wad.py list [WAD]
    python tools/wad.py extract OUT_DIR [WAD]
"""
import os
import struct
import sys

TOC_OFFSET = 0x800
MAGIC = b'PWF '

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'bin', 'Release', 'net10.0', 'disc', 'DATA', 'WAD.WAD')


class Wad:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.fh = open(self.path, 'rb')
        head = self.fh.read(16)
        if head[:4] != MAGIC:
            raise RuntimeError(f'{self.path}: not a PWF archive')
        self.length, self.version, self.count = struct.unpack('<III', head[4:16])
        self.fh.seek(TOC_OFFSET)
        raw = self.fh.read(self.count * 8)
        self.toc = [struct.unpack('<II', raw[i * 8:i * 8 + 8]) for i in range(self.count)]

    def entry(self, index):
        offset, size = self.toc[index]
        self.fh.seek(offset)
        return self.fh.read(size)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    path = sys.argv[3] if len(sys.argv) > 3 else (
        sys.argv[2] if cmd == 'list' and len(sys.argv) > 2 else DEFAULT)
    wad = Wad(path)
    if cmd == 'list':
        print(f'{wad.count} entries, archive length {wad.length}')
        for i, (offset, size) in enumerate(wad.toc):
            print(f'{i:4d} 0x{offset:08x} {size:9d}')
    elif cmd == 'extract':
        out = os.path.abspath(sys.argv[2])
        os.makedirs(out, exist_ok=True)
        for i in range(wad.count):
            with open(os.path.join(out, f'{i:04d}.bin'), 'wb') as fh:
                fh.write(wad.entry(i))
        print(f'extracted {wad.count} entries to {out}')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
