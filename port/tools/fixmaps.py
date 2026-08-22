"""
Rebuilds the function maps for the X-Men: Mutant Academy 2 port.

RecompOne's own scan treats every 32-bit word in the image as a potential
instruction, so data that happens to decode as `jal` invents function starts in the
middle of real functions. Each invented start caps the previous function's extent and
the recompiler emits a function that "returns" halfway through, which shows up at
runtime as `unmapped call: <address just past the truncation>`.

This pass rebuilds the map from three trustworthy sources instead:

  1. Symbols identified by matching the PsyQ 4.7 libraries against the executable
     (config/funcmaps/psyq_main.json) plus hand-verified names (manual.json).
  2. Pointer targets -- raw pointer words and lui/addiu pairs from any module -- that
     land on a real boundary. This is how the libgpu driver vtable and the
     per-character overlay vtables are reached; many of those are leaf functions with
     no stack frame, which RecompOne's prologue heuristic cannot see.
  3. `jal` targets, but only those read from inside a function whose extent we have
     already proven ends in a return or a trap. Data never gets scanned this way, so
     it cannot invent starts.

A "real boundary" is the first word of the module, or a word whose predecessor is the
delay slot of an unconditional transfer or a trap (nop padding skipped). Nothing can
fall through into such an address, so promoting one can never merge or corrupt a
neighbouring function.

Extents are then recomputed the way the recompiler would: walk forward tracking the
furthest forward branch target, and stop at the first return or trap at or past it.

Usage:  python tools/fixmaps.py <port-dir>
Inputs:  config/funcmaps/<module>_sweep.json, psyq_main.json, manual.json
Outputs: config/funcmaps/<module>.json
"""
import json
import os
import struct
import sys

SECTOR = 2352
CHARS = "BEA CYC FOR GAM HAV JUG MAG MYS NIG PHO PSY ROG SAB SPI STO TOA WOL XAV".split()

# Highest address that still holds code in the main executable: the PsyQ libraries end
# just before the game's string pool at 0x80094F04.
MAIN_TEXT_LIMIT = 0x80094F04
MAIN_ENTRY = 0x8006AE18


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def read_iso(bin_path):
    f = open(bin_path, 'rb')

    def user(lba):
        f.seek(lba * SECTOR)
        s = f.read(SECTOR)
        return s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048]

    def extent(lba, length):
        out = bytearray()
        for i in range((length + 2047) // 2048):
            out += user(lba + i)
        return bytes(out[:length])

    def parse_dir(lba, length):
        data = extent(lba, length)
        entries = []
        off = 0
        while off < len(data):
            rl = data[off]
            if rl == 0:
                off = (off // 2048 + 1) * 2048
                if off >= len(data):
                    break
                continue
            e = data[off:off + rl]
            entries.append((
                e[33:33 + e[32]].decode('latin1').split(';')[0],
                struct.unpack('<I', e[2:6])[0],
                struct.unpack('<I', e[10:14])[0],
                (e[25] & 2) != 0))
            off += rl
        return entries

    pvd = user(16)
    root_lba = struct.unpack('<I', pvd[158:162])[0]
    root_len = struct.unpack('<I', pvd[166:170])[0]
    files = {}

    def walk(lba, length, path):
        for (name, elba, elen, isdir) in parse_dir(lba, length):
            if name in ('\x00', '\x01'):
                continue
            p = path + '/' + name
            if isdir:
                walk(elba, elen, p)
            else:
                files[p.lstrip('/').upper()] = (elba, elen)

    walk(root_lba, root_len, '')
    return files, extent


def is_padding(w):
    """nop, or the `sll zero, zero, 0` variants the linker pads with"""
    return w == 0 or ((w >> 26) == 0 and (w & 0x3F) == 0 and ((w >> 11) & 31) == 0)


def is_trap(w):
    return (w >> 26) == 0 and (w & 0x3F) in (0x0C, 0x0D)      # syscall, break


def is_uncond_transfer(w):
    return (w >> 26) == 2 or ((w >> 26) == 0 and (w & 0x3F) == 8)   # j, jr


class Module:
    def __init__(self, name, data, base, limit=None):
        self.name = name
        self.base = base
        self.n = len(data) // 4
        self.end = base + self.n * 4
        self.limit = min(limit, self.end) if limit else self.end
        self.w = [struct.unpack_from('<I', data, i * 4)[0] for i in range(self.n)]

    def contains(self, a):
        return self.base <= a < self.limit and (a & 3) == 0

    def idx(self, a):
        return (a - self.base) // 4

    def constants(self):
        out = set()
        lui = {}
        for w in self.w:
            if (w & 3) == 0 and 0x80010000 <= w < 0x80200000:
                out.add(w)
            op = w >> 26
            rs = (w >> 21) & 31
            rt = (w >> 16) & 31
            imm = w & 0xFFFF
            if op == 0x0F:
                lui[rt] = imm
            elif op == 0x09:
                if rs in lui:
                    out.add(((lui[rs] << 16) + s16(imm)) & 0xFFFFFFFF)
                if rt != rs:
                    lui.pop(rt, None)
            elif op == 0x0D:
                if rs in lui:
                    out.add(((lui[rs] << 16) | imm) & 0xFFFFFFFF)
                if rt != rs:
                    lui.pop(rt, None)
        return {a for a in out if (a & 3) == 0}

    def is_boundary(self, i):
        """True when nothing can fall through into instruction i."""
        if i == 0:
            return True
        k = i - 1
        while k >= 0 and is_padding(self.w[k]):
            k -= 1
        if k < 0:
            return True
        # w[k] is either the transfer itself (its delay slot was padding we skipped)
        # or the delay slot of the transfer at w[k-1].
        if is_trap(self.w[k]) or is_uncond_transfer(self.w[k]):
            return True
        j = k - 1
        return j >= 0 and (is_uncond_transfer(self.w[j]) or is_trap(self.w[j]))

    def plausible(self, i):
        w = self.w[i]
        if is_padding(w):
            return False
        op = w >> 26
        fn = w & 0x3F
        if op == 0:
            return fn in (0, 2, 3, 4, 6, 7, 8, 9, 12, 13, 16, 17, 18, 19, 24, 25, 26,
                          27, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43)
        if op == 1:
            return ((w >> 16) & 31) in (0, 1, 0x10, 0x11)
        if 2 <= op <= 15 or op in (16, 18):
            return True
        return op in (32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 46, 50, 58)

    def extent(self, start, limit):
        """(end, terminated) -- terminated means we proved where the function stops."""
        i = self.idx(start)
        li = min(self.idx(limit), self.n)
        reach = start
        while i < li:
            a = self.base + i * 4
            w = self.w[i]
            op = w >> 26
            if not self.plausible(i) and not is_padding(w):
                return a, False
            tgt = None
            if op == 2:
                tgt = 0x80000000 | ((w & 0x03FFFFFF) << 2)
            elif op == 1 or 4 <= op <= 7:
                tgt = (a + 4 + s16(w & 0xFFFF) * 4) & 0xFFFFFFFF
            if tgt is not None and start < tgt < limit and tgt > reach:
                reach = tgt
            if a >= reach:
                if op == 0 and (w & 0x3F) == 8 and ((w >> 21) & 31) == 31:   # jr ra
                    return min(a + 8, limit), True
                # A div-by-zero `break` always has a branch jumping over it, so reach
                # would still be ahead of us; past reach it is genuinely unreachable
                # tail padding (this is how `main` ends).
                if op == 0 and (w & 0x3F) == 0x0D:
                    return min(a + 4, limit), True
            i += 1
        return limit, False

    def call_targets(self, start, end, body_end=None):
        """jal targets, plus branch/jump targets that leave the function.

        libgte's entry points share one body: VectorNormalS is three loads and a
        `b` into the middle of VectorNormalSS. The recompiler turns any transfer
        that leaves a function into a dispatched call, so those escape targets have
        to be function starts too or the call lands on nothing.
        """
        out = []
        if body_end is None:
            body_end = end
        i = self.idx(start)
        li = min(self.idx(end), self.n)
        while i < li:
            a = self.base + i * 4
            w = self.w[i]
            op = w >> 26
            if op == 3:
                out.append(0x80000000 | ((w & 0x03FFFFFF) << 2))
            elif op == 2:
                t = 0x80000000 | ((w & 0x03FFFFFF) << 2)
                if not (start <= t < body_end):
                    out.append(t)
            elif op in (4, 5) and ((w >> 21) & 31) == ((w >> 16) & 31):
                # `b` (beq zero, zero) -- an always-taken branch. Conditional branches
                # that appear to escape usually just mean this extent came out short,
                # and promoting their targets would shred real functions.
                t = (a + 4 + s16(w & 0xFFFF) * 4) & 0xFFFFFFFF
                if op == 4 and not (start <= t < body_end):
                    out.append(t)
            i += 1
        return out


def load_forced(path):
    """{"modules": {"<name>": [{"address": ..., "name": ...}]}}"""
    if not os.path.exists(path):
        return {}
    doc = json.load(open(path))
    return {mod: {int(e['address'], 16): e['name'] for e in entries}
            for mod, entries in doc.get('modules', {}).items()}


def forced_for(forced, m):
    """Entries recorded for this module, plus ones main calls into its address range.

    A constant call from main into overlay space cannot say which overlay was resident,
    so it applies to every module that covers the address; entries found inside an
    overlay's own code stay with that overlay.

    Targets that do not decode as an instruction are skipped: those come from
    jump-table analysis running off the end of a real table into the data that follows,
    so the call site is unreachable. Forcing a function onto data would only emit one
    junk instruction that falls through into the next address, which then shows up as
    the next missing target, and so on down the table.
    """
    out = {}
    for a, nm in forced.get(m.name, {}).items():
        if m.contains(a) and m.plausible(m.idx(a)):
            out[a] = nm
    if m.name != 'main':
        for a, nm in forced.get('main', {}).items():
            if m.contains(a) and m.plausible(m.idx(a)):
                out.setdefault(a, nm)
    return out


def load_map(path):
    if not os.path.exists(path):
        return {}
    return {int(f['address'], 16): f.get('name', '') for f in json.load(open(path))['functions']}


def build(m, hard, soft, external):
    """Greedy walk over the candidate starts.

    Extents are natural: walk forward tracking the furthest forward branch target and
    stop at the first return past it. They are deliberately *not* clipped at the next
    known start, because a function can legitimately be entered in the middle -- libgte
    stacks three entry points on one body, and jump tables land inside big switch
    functions. Clipping there was self-reinforcing: the clipped function emitted a call
    to its own tail, that call became another forced start, and the next clip landed
    earlier still. Overlapping ranges cost a little duplicated output and keep every
    entry point correct.

    A candidate that merely follows an unconditional jump is not necessarily a
    function: compilers routinely lay out `j <epilogue>` immediately before a block
    earlier code branches into. Those (soft) candidates are dropped when an accepted
    function's extent already covers them. Hard starts -- `jal` targets, escapes, and
    the seeds we trust outright -- are always kept.
    """
    hard = dict(hard)

    def extent_of(a, starts):
        nat_end, term = m.extent(a, m.limit)
        if term:
            return nat_end, True
        nxt = m.limit
        for s2 in starts:
            if s2 > a:
                nxt = min(s2, m.limit)
                break
        end, _ = m.extent(a, nxt)
        return (end if end > a else min(a + 4, nxt)), False

    accepted = {}
    for _ in range(24):
        accepted = {}
        starts = sorted(set(hard) | set(soft))
        spans = {}
        covered_to = 0
        for k, a in enumerate(starts):
            if a not in hard and a < covered_to:
                continue
            end, term = extent_of(a, starts[k + 1:])
            accepted[a] = hard.get(a) or soft.get(a) or ('func_%08X' % a)
            spans[a] = (end, term)
            if end > covered_to:
                covered_to = end

        found = 0
        external.clear()
        for a, (end, term) in spans.items():
            if not term and a not in hard:
                continue
            for t in m.call_targets(a, end, end):
                if m.contains(t):
                    if t not in hard:
                        hard[t] = 'func_%08X' % t
                        found += 1
                else:
                    external.add(t)
        if found == 0:
            break

    starts = sorted(accepted)
    out = []
    for k, a in enumerate(starts):
        end, _ = extent_of(a, starts[k + 1:])
        out.append({"address": '0x%08X' % a, "name": accepted[a], "size": end - a})
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    fmdir = os.path.join(root, 'config', 'funcmaps')
    binpath = os.path.join(root, '..', 'X-Men - Mutant Academy 2 (USA) (Track 01).bin')
    files, extent = read_iso(binpath)

    layout = [('main', 'SLUS_013.82', 0x80010000, 0x800, MAIN_TEXT_LIMIT)]
    for c in CHARS:
        layout.append(('%s_rel1' % c, 'DATA/REL_CODE/ONE/%s_REL1.R' % c, 0x80107EF0, 0, None))
        layout.append(('%s_rel2' % c, 'DATA/REL_CODE/TWO/%s_REL2.R' % c, 0x80110EF0, 0, None))
    layout.append(('front', 'DATA/FRONT.BIN', 0x801C9000, 0, None))
    layout.append(('practice', 'DATA/PRACTICE.BIN', 0x801EF000, 0, None))

    mods = []
    for name, path, base, skip, limit in layout:
        key = path.upper()
        if key not in files:
            print('!! missing on disc: %s' % path)
            continue
        lba, length = files[key]
        mods.append(Module(name, extent(lba, length)[skip:], base, limit))
    print('modules: %d' % len(mods))

    constants = set()
    for m in mods:
        constants |= m.constants()
    print('pointer constants: %d' % len(constants))

    psyq = load_map(os.path.join(fmdir, 'psyq_main.json'))
    manual = load_map(os.path.join(fmdir, 'manual.json'))
    # Addresses the recompiled code calls but nothing defines; see tools/closure.py.
    forced = load_forced(os.path.join(fmdir, 'forced.json'))

    grand = 0
    external = set()
    for _pass in range(3):
        found = set()
        for m in mods:
            hard = {}
            if m.name == 'main':
                hard[MAIN_ENTRY] = 'entry_point'
            for src in (psyq, manual):
                for a, nm in src.items():
                    if m.contains(a):
                        hard[a] = nm
            for a, nm in forced_for(forced, m).items():
                hard.setdefault(a, nm)
            for a in external:
                if m.contains(a):
                    hard.setdefault(a, 'func_%08X' % a)
            soft = {}
            for a in sorted(c for c in constants if m.contains(c)):
                if a not in hard and m.plausible(m.idx(a)) and m.is_boundary(m.idx(a)):
                    soft[a] = 'ptr_%08X' % a
            sweep = load_map(os.path.join(fmdir, m.name + '_sweep.json'))
            for a, nm in sweep.items():
                if a not in hard and a not in soft and m.contains(a)                         and m.plausible(m.idx(a)) and m.is_boundary(m.idx(a)):
                    soft[a] = nm
            out = set()
            build(m, hard, soft, out)
            found |= out
        before = len(external)
        external |= found
        if len(external) == before:
            break
    print('cross-module call targets: %d' % len(external))

    for m in mods:
        hard = {}
        if m.name == 'main':
            hard[MAIN_ENTRY] = 'entry_point'
        for src in (psyq, manual):
            for a, nm in src.items():
                if m.contains(a):
                    hard[a] = nm
        nseed = len(hard)
        for a, nm in forced_for(forced, m).items():
            hard.setdefault(a, nm)
        ncross = 0
        for a in external:
            if m.contains(a) and a not in hard:
                hard[a] = 'func_%08X' % a
                ncross += 1
        soft = {}
        for a in sorted(c for c in constants if m.contains(c)):
            if a not in hard and m.plausible(m.idx(a)) and m.is_boundary(m.idx(a)):
                soft[a] = 'ptr_%08X' % a
        nptr = len(soft)

        sweep = load_map(os.path.join(fmdir, m.name + '_sweep.json'))
        for a, nm in sweep.items():
            if a not in hard and a not in soft and m.contains(a)                     and m.plausible(m.idx(a)) and m.is_boundary(m.idx(a)):
                soft[a] = nm
        out = build(m, hard, soft, set())
        json.dump({"functions": out}, open(os.path.join(fmdir, m.name + '.json'), 'w'), indent=1)
        grand += len(out)
        print('%-10s %4d functions  (seed %d, cross %d, ptr %d, sweep-in %d)'
              % (m.name, len(out), nseed, ncross, nptr, len(sweep)))
    print('total %d functions' % grand)


main()
