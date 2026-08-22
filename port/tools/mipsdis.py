import struct, sys, json, os

REG = ['zero','at','v0','v1','a0','a1','a2','a3','t0','t1','t2','t3','t4','t5','t6','t7',
       's0','s1','s2','s3','s4','s5','s6','s7','t8','t9','k0','k1','gp','sp','fp','ra']

SPECIAL = {0x00:'sll',0x02:'srl',0x03:'sra',0x04:'sllv',0x06:'srlv',0x07:'srav',
           0x08:'jr',0x09:'jalr',0x0c:'syscall',0x0d:'break',0x10:'mfhi',0x11:'mthi',
           0x12:'mflo',0x13:'mtlo',0x18:'mult',0x19:'multu',0x1a:'div',0x1b:'divu',
           0x20:'add',0x21:'addu',0x22:'sub',0x23:'subu',0x24:'and',0x25:'or',
           0x26:'xor',0x27:'nor',0x2a:'slt',0x2b:'sltu'}

OPS = {0x02:'j',0x03:'jal',0x04:'beq',0x05:'bne',0x06:'blez',0x07:'bgtz',
       0x08:'addi',0x09:'addiu',0x0a:'slti',0x0b:'sltiu',0x0c:'andi',0x0d:'ori',
       0x0e:'xori',0x0f:'lui',0x20:'lb',0x21:'lh',0x22:'lwl',0x23:'lw',0x24:'lbu',
       0x25:'lhu',0x26:'lwr',0x28:'sb',0x29:'sh',0x2a:'swl',0x2b:'sw',0x2e:'swr',
       0x30:'lwc0',0x31:'lwc1',0x32:'lwc2',0x38:'swc0',0x39:'swc1',0x3a:'swc2'}


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def dis(w, pc):
    op = w >> 26
    rs = (w >> 21) & 31
    rt = (w >> 16) & 31
    rd = (w >> 11) & 31
    sa = (w >> 6) & 31
    fn = w & 0x3f
    imm = w & 0xffff
    if w == 0:
        return 'nop', None
    if op == 0:
        nm = SPECIAL.get(fn, 'sp?%02x' % fn)
        if nm in ('sll', 'srl', 'sra'):
            return '%s %s, %s, %d' % (nm, REG[rd], REG[rt], sa), None
        if nm in ('jr',):
            return 'jr %s' % REG[rs], None
        if nm == 'jalr':
            return 'jalr %s, %s' % (REG[rd], REG[rs]), None
        if nm in ('mfhi', 'mflo'):
            return '%s %s' % (nm, REG[rd]), None
        if nm in ('mthi', 'mtlo'):
            return '%s %s' % (nm, REG[rs]), None
        if nm in ('mult', 'multu', 'div', 'divu'):
            return '%s %s, %s' % (nm, REG[rs], REG[rt]), None
        if nm in ('syscall', 'break'):
            return nm, None
        return '%s %s, %s, %s' % (nm, REG[rd], REG[rs], REG[rt]), None
    if op == 1:
        nm = {0: 'bltz', 1: 'bgez', 0x10: 'bltzal', 0x11: 'bgezal'}.get(rt, 'b?%02x' % rt)
        t = pc + 4 + s16(imm) * 4
        return '%s %s, 0x%08X' % (nm, REG[rs], t), t
    if op == 0x10:
        if rs == 0:
            return 'mfc0 %s, $%d' % (REG[rt], rd), None
        if rs == 4:
            return 'mtc0 %s, $%d' % (REG[rt], rd), None
        if rs == 0x10:
            return 'rfe', None
        return 'cop0 0x%08x' % w, None
    if op == 0x12:
        if rs == 0:
            return 'mfc2 %s, $%d' % (REG[rt], rd), None
        if rs == 2:
            return 'cfc2 %s, $%d' % (REG[rt], rd), None
        if rs == 4:
            return 'mtc2 %s, $%d' % (REG[rt], rd), None
        if rs == 6:
            return 'ctc2 %s, $%d' % (REG[rt], rd), None
        return 'gte 0x%07x' % (w & 0x1ffffff), None
    nm = OPS.get(op, 'op?%02x' % op)
    if nm in ('j', 'jal'):
        t = (pc & 0xf0000000) | ((w & 0x03ffffff) << 2)
        return '%s 0x%08X' % (nm, t), t
    if nm in ('beq', 'bne'):
        t = pc + 4 + s16(imm) * 4
        return '%s %s, %s, 0x%08X' % (nm, REG[rs], REG[rt], t), t
    if nm in ('blez', 'bgtz'):
        t = pc + 4 + s16(imm) * 4
        return '%s %s, 0x%08X' % (nm, REG[rs], t), t
    if nm == 'lui':
        return 'lui %s, 0x%04X' % (REG[rt], imm), None
    if nm in ('addi', 'addiu', 'slti', 'sltiu'):
        return '%s %s, %s, %d' % (nm, REG[rt], REG[rs], s16(imm)), None
    if nm in ('andi', 'ori', 'xori'):
        return '%s %s, %s, 0x%04X' % (nm, REG[rt], REG[rs], imm), None
    return '%s %s, %d(%s)' % (nm, REG[rt], s16(imm), REG[rs]), None


class Image:
    def __init__(self, path, base, skip=0):
        d = open(path, 'rb').read()
        self.d = d[skip:]
        self.base = base

    def word(self, addr):
        o = addr - self.base
        if o < 0 or o + 4 > len(self.d):
            return None
        return struct.unpack_from('<I', self.d, o)[0]

    def dump(self, addr, n, syms=None):
        for i in range(n):
            a = addr + i * 4
            w = self.word(a)
            if w is None:
                print('%08X: <oob>' % a)
                continue
            t, tgt = dis(w, a)
            lbl = ''
            if syms and tgt is not None and tgt in syms:
                lbl = '  <%s>' % syms[tgt]
            sl = ''
            if syms and a in syms:
                sl = '  ; %s' % syms[a]
            print('%08X: %08X  %-34s%s%s' % (a, w, t, lbl, sl))


if __name__ == '__main__':
    exe = sys.argv[1]
    base = int(sys.argv[2], 16)
    addr = int(sys.argv[3], 16)
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 24
    symf = sys.argv[5] if len(sys.argv) > 5 else None
    syms = None
    if symf and os.path.exists(symf):
        raw = json.load(open(symf))
        syms = {}
        if isinstance(raw, dict) and 'functions' in raw:
            for f in raw['functions']:
                syms[int(f['address'], 16)] = f['name']
        else:
            for k, v in raw.items():
                syms[int(v, 16)] = k
    skip = 0x800 if open(exe, 'rb').read(8) == b'PS-X EXE' else 0
    Image(exe, base, skip).dump(addr, n, syms)
