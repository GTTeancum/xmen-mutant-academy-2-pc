"""Read the ISO 9660 filesystem out of a MODE2/2352 PlayStation disc image.

The data track stores 2352-byte sectors: 12 bytes of sync, a 4-byte header, an 8-byte
Mode 2 subheader, then the 2048 bytes that ISO 9660 actually addresses, then EDC/ECC.
Everything here works in logical sectors and pulls the 2048-byte payload out, so the
rest of the tooling can pretend it is looking at a plain ISO.

Usage:
    python tools/disc.py list                 # every file, with LBA and size
    python tools/disc.py extract OUT_DIR      # write the whole tree to disk
"""
import os
import struct
import sys

RAW_SECTOR = 2352
USER_OFFSET = 24          # sync (12) + header (4) + subheader (8)
USER_SIZE = 2048

DISC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', '..', 'X-Men - Mutant Academy 2 (USA) (Track 01).bin')


class Disc:
    def __init__(self, path=DISC):
        self.path = os.path.abspath(path)
        self.fh = open(self.path, 'rb')
        self.sectors = os.path.getsize(self.path) // RAW_SECTOR

    def sector(self, lba):
        """The 2048 user bytes of one logical sector."""
        self.fh.seek(lba * RAW_SECTOR + USER_OFFSET)
        return self.fh.read(USER_SIZE)

    def read(self, lba, length):
        out = bytearray()
        while len(out) < length:
            out += self.sector(lba)
            lba += 1
        return bytes(out[:length])


def _name(raw):
    n = raw.decode('latin-1')
    return n.split(';')[0]


def _entries(data):
    """Walk one directory extent, yielding (name, lba, size, is_dir)."""
    i = 0
    while i < len(data):
        length = data[i]
        if length == 0:
            # Directory records never straddle a sector; a zero length means the rest
            # of this sector is padding.
            i = (i // USER_SIZE + 1) * USER_SIZE
            if i >= len(data):
                break
            continue
        rec = data[i:i + length]
        lba = struct.unpack('<I', rec[2:6])[0]
        size = struct.unpack('<I', rec[10:14])[0]
        flags = rec[25]
        nlen = rec[32]
        name = rec[33:33 + nlen]
        if nlen == 1 and name in (b'\x00', b'\x01'):    # . and ..
            i += length
            continue
        yield _name(name), lba, size, bool(flags & 2)
        i += length


def walk(disc):
    """Every file on the disc, depth first, as (path, lba, size)."""
    pvd = disc.sector(16)
    if pvd[1:6] != b'CD001':
        raise RuntimeError('no ISO 9660 primary volume descriptor at sector 16')
    root = pvd[156:156 + 34]
    root_lba = struct.unpack('<I', root[2:6])[0]
    root_size = struct.unpack('<I', root[10:14])[0]

    stack = [('', root_lba, root_size)]
    while stack:
        prefix, lba, size = stack.pop()
        data = disc.read(lba, size)
        for name, child_lba, child_size, is_dir in _entries(data):
            path = f'{prefix}/{name}' if prefix else name
            if is_dir:
                stack.append((path, child_lba, child_size))
            else:
                yield path, child_lba, child_size


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    disc = Disc()
    files = sorted(walk(disc))
    if cmd == 'list':
        total = 0
        for path, lba, size in files:
            print(f'{lba:8d} {size:10d}  {path}')
            total += size
        print(f'{len(files)} files, {total / 1048576:.1f} MB')
    elif cmd == 'extract':
        out = os.path.abspath(sys.argv[2])
        for path, lba, size in files:
            dst = os.path.join(out, path.replace('/', os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as fh:
                fh.write(disc.read(lba, size))
        print(f'extracted {len(files)} files to {out}')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
