"""
Closes the gap between what the recompiled code calls and what it defines.

RecompOne turns any control transfer that leaves a function -- a call, a tail jump, a
jump-table entry, or simply running off the end -- into `Dispatcher.Call(c, m, addr)`.
If nothing was emitted at `addr`, that call throws `unmapped call: 0x...` the first
time the game takes that path, which can be minutes into a session and only on some
branches. Finding those by playing is hopeless; they are all visible in the generated
C# instead.

This scans generated/<module>.cs for constant call targets, subtracts everything the
dispatch tables define, and records the remainder per module in
config/funcmaps/forced.json, which fixmaps.py promotes to function starts. Attribution
matters: the eighteen per-character overlays all load at the same address, so a target
found in BEA_rel1.cs must not be forced into the other seventeen.

Usage: python tools/closure.py <port-dir>
Exit code 0 once nothing is missing.
"""
import json
import os
import re
import sys

CALL = re.compile(r'Dispatcher\.Call\(c, m, 0x([0-9A-Fa-f]{8})u\)')
DEFN = re.compile(r'^\s*\[0x([0-9A-Fa-f]{8})u\] = ')


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    gen = os.path.join(root, 'generated')
    path = os.path.join(root, 'config', 'funcmaps', 'forced.json')

    called = {}          # module -> set(addr)
    defined = set()
    for name in sorted(os.listdir(gen)):
        if not name.endswith('.cs') or name in ('Entry.cs', 'Stubs.cs'):
            continue
        module = name[:-3]
        hits = called.setdefault(module, set())
        with open(os.path.join(gen, name), encoding='utf-8') as fh:
            for line in fh:
                for m in CALL.finditer(line):
                    hits.add(int(m.group(1), 16))
                d = DEFN.match(line)
                if d:
                    defined.add(int(d.group(1), 16))

    doc = {"modules": {}}
    if os.path.exists(path):
        doc = json.load(open(path))
        doc.setdefault('modules', {})

    total_missing = 0
    for module, hits in sorted(called.items()):
        missing = sorted(a for a in hits - defined if 0x80010000 <= a < 0x80200000)
        if not missing:
            continue
        total_missing += len(missing)
        entries = {int(e['address'], 16): e['name']
                   for e in doc['modules'].get(module, [])}
        for a in missing:
            entries.setdefault(a, 'call_%08X' % a)
        doc['modules'][module] = [{"address": '0x%08X' % a, "name": entries[a]}
                                  for a in sorted(entries)]
        print('%-10s missing %d (e.g. %s)' % (
            module, len(missing), ' '.join('%08X' % a for a in missing[:4])))

    json.dump(doc, open(path, 'w'), indent=1)
    print('missing %d' % total_missing)
    return 1 if total_missing else 0


sys.exit(main())
