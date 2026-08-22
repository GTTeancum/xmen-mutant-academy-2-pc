"""
Recovers PsyQ SDK symbol names from the game executable.

X-Men: Mutant Academy 2 has no decompilation, but it statically links PsyQ 4.7, and
RecompOne routes SDK calls to its runtime *by name* -- so recovering those names is
what lets the port serve libgpu, libcd, libpad and libcdstream at all.

Each library function is matched against the executable as a byte pattern with its
relocated fields masked out (the jal target, the halves of a lui/addiu pair), which is
the same idea as an IDA FLIRT signature. Where several one-instruction stubs share a
shape, they are told apart by their relocations: derive the address each candidate
implies for the symbols it references, and keep the reading consistent with symbols
already placed. That resolves all but a handful, which config/funcmaps/manual.json
pins by hand.

Needs the PsyQ 4.7 libraries converted to ELF objects (psx.arthus.net hosts a
conversion); point it at the directory holding libcd/, libgpu/, ... .

Usage: python tools/psyq_signatures.py <exe> <base-hex> <psyq-lib-dir> [out.json]
   e.g. python tools/psyq_signatures.py SLUS_013.82 80010000 psyq/lib psyq_main.json
"""
import struct, os, glob, sys, json, collections
from elflib import Elf

MASK_BY_RELOC = {0: 0xFFFFFFFF, 1: 0xFFFF0000, 2: 0x00000000, 3: 0x00000000, 4: 0xFC000000,
                 5: 0xFFFF0000, 6: 0xFFFF0000, 7: 0xFFFF0000, 8: 0xFFFF0000, 9: 0xFFFF0000,
                 10: 0xFFFF0000, 11: 0xFFFF0000, 12: 0x00000000}


class LibFunc:
    __slots__ = ('name', 'obj', 'words', 'masks', 'relocs', 'size')

    def __init__(self, name, obj, words, masks, relocs):
        self.name = name
        self.obj = obj
        self.words = words
        self.masks = masks
        self.relocs = relocs
        self.size = len(words) * 4


def extract(objpath):
    e = Elf(objpath)
    text = e.sec('.text')
    if text is None or text['size'] == 0:
        return []
    tidx = text['index']
    data = e.secdata(text)
    nwords = len(data) // 4
    words = [struct.unpack_from(e.e + 'I', data, i * 4)[0] for i in range(nwords)]
    masks = [0xFFFFFFFF] * nwords
    syms = e.symbols()
    relmap = collections.defaultdict(list)
    for (off, symidx, typ) in e.relocs('.text'):
        w = off // 4
        if w >= nwords:
            continue
        masks[w] &= MASK_BY_RELOC.get(typ, 0)
        sname = syms[symidx]['name'] if symidx < len(syms) else ''
        relmap[w].append((typ, sname))
    fsyms = [s for s in syms if s['shndx'] == tidx and s['name']
             and not s['name'].startswith('$') and s['type'] != 3]
    fsyms.sort(key=lambda s: s['value'])
    out = []
    for i, s in enumerate(fsyms):
        st = s['value']
        en = fsyms[i + 1]['value'] if i + 1 < len(fsyms) else len(data)
        if en <= st:
            continue
        a, b = st // 4, en // 4
        rel = {(w - a): relmap[w] for w in range(a, b) if w in relmap}
        out.append(LibFunc(s['name'], os.path.basename(objpath), words[a:b], masks[a:b], rel))
    return out


def load_objs(libroot):
    funcs = []
    for o in sorted(glob.glob(os.path.join(libroot, '*', '*.o'))):
        try:
            funcs.extend(extract(o))
        except Exception as ex:
            print('skip', o, ex, file=sys.stderr)
    return funcs


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def main():
    exe = sys.argv[1]
    base = int(sys.argv[2], 16)
    libroot = sys.argv[3]
    out = sys.argv[4] if len(sys.argv) > 4 else None
    data = open(exe, 'rb').read()
    code = data[0x800:] if data[:8] == b'PS-X EXE' else data
    n = len(code) // 4
    tgt = [struct.unpack_from('<I', code, i * 4)[0] for i in range(n)]
    funcs = load_objs(libroot)
    print('lib functions: %d' % len(funcs))

    wordpos = collections.defaultdict(list)
    for i, w in enumerate(tgt):
        wordpos[w].append(i)

    sites = collections.defaultdict(list)
    for f in funcs:
        if len(f.words) < 3:
            continue
        anchor = None
        for i, mk in enumerate(f.masks):
            if mk == 0xFFFFFFFF:
                anchor = (i, f.words[i])
                break
        if anchor is None:
            continue
        ai, av = anchor
        for j in wordpos.get(av, ()):
            s = j - ai
            if s < 0 or s + len(f.words) > n:
                continue
            ok = True
            for k in range(len(f.words)):
                mk = f.masks[k]
                if mk and (tgt[s + k] & mk) != (f.words[k] & mk):
                    ok = False
                    break
            if ok:
                sites[base + s * 4].append(f)

    print('raw match sites: %d' % len(sites))

    def derive(addr, f):
        got = {}
        s = (addr - base) // 4
        pend_hi = {}
        for k, rl in f.relocs.items():
            gw = tgt[s + k]
            ow = f.words[k]
            for (typ, sname) in rl:
                if not sname or sname.startswith('$') or sname.startswith('.'):
                    continue
                if typ == 4:
                    A = (ow & 0x03FFFFFF) << 2
                    T = 0x80000000 | ((gw & 0x03FFFFFF) << 2)
                    got[sname] = (T - A) & 0xFFFFFFFF
                elif typ == 5:
                    pend_hi[sname] = (ow & 0xFFFF, gw & 0xFFFF)
                elif typ == 6:
                    if sname in pend_hi:
                        ohi, ghi = pend_hi.pop(sname)
                        A = ((ohi << 16) + s16(ow & 0xFFFF)) & 0xFFFFFFFF
                        G = ((ghi << 16) + s16(gw & 0xFFFF)) & 0xFFFFFFFF
                        got[sname] = (G - A) & 0xFFFFFFFF
        return got

    resolved = {}
    byname = collections.defaultdict(set)
    for addr, fs in sites.items():
        names = set(f.name for f in fs)
        if len(names) == 1:
            byname[names.pop()].add(addr)
    for nm, addrs in byname.items():
        if len(addrs) == 1:
            resolved[nm] = next(iter(addrs))

    for it in range(8):
        symaddr = collections.defaultdict(collections.Counter)
        for nm, addr in list(resolved.items()):
            for f in sites.get(addr, ()):
                if f.name != nm:
                    continue
                for k, v in derive(addr, f).items():
                    symaddr[k][v] += 1
        for k, c in symaddr.items():
            if k in resolved:
                continue
            top = c.most_common(1)[0]
            if len(c) == 1 or top[1] > 1:
                resolved[k] = top[0]

        changed = False
        for addr, fs in sites.items():
            names = set(f.name for f in fs)
            if len(names) <= 1:
                continue
            cands = []
            for f in fs:
                if f.name in resolved and resolved[f.name] != addr:
                    continue
                d = derive(addr, f)
                score = 0
                bad = False
                for k, v in d.items():
                    if k in resolved:
                        if resolved[k] == v:
                            score += 1
                        else:
                            bad = True
                if bad:
                    continue
                cands.append((score, f))
            if not cands:
                continue
            mx = max(c[0] for c in cands)
            topnames = set(f.name for sc, f in cands if sc == mx)
            if len(topnames) == 1 and mx > 0:
                nm = topnames.pop()
                if nm not in resolved:
                    resolved[nm] = addr
                    changed = True
        if not changed and it > 1:
            break

    res = []
    for addr, fs in sorted(sites.items()):
        names = sorted(set(f.name for f in fs))
        chosen = [nm for nm in names if resolved.get(nm) == addr]
        size = max(f.size for f in fs)
        res.append((addr, chosen if chosen else names, size, fs[0].obj, len(chosen) == 1))
    for addr, names, size, obj, uniq in res:
        flag = '  ' if uniq else '??'
        print('%08X %s %s  (%d bytes, %s)' % (addr, flag, ','.join(names), size, obj))
    print('sites=%d resolvedNames=%d' % (len(res), len(resolved)))
    if out:
        j = {"functions": [{"address": '0x%08X' % a, "name": nm[0], "size": sz}
                           for a, nm, sz, ob, u in res if u]}
        json.dump(j, open(out, 'w'), indent=1)
        print('wrote %s (%d)' % (out, len(j['functions'])))
        json.dump({k: '0x%08X' % v for k, v in sorted(resolved.items())},
                  open(out + '.syms.json', 'w'), indent=1)


main()
