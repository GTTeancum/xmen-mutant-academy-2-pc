import struct, os, glob

R_MIPS_NONE=0; R_MIPS_16=1; R_MIPS_32=2; R_MIPS_REL32=3; R_MIPS_26=4
R_MIPS_HI16=5; R_MIPS_LO16=6; R_MIPS_GPREL16=7; R_MIPS_LITERAL=8
R_MIPS_GOT16=9; R_MIPS_PC16=10; R_MIPS_CALL16=11; R_MIPS_GPREL32=12

class Elf:
    def __init__(self, path):
        self.path=path
        d=open(path,'rb').read()
        self.d=d
        assert d[:4]==b'\x7fELF'
        assert d[4]==1
        little = d[5]==1
        self.e = '<' if little else '>'
        (self.e_type, self.e_machine, self.e_version, self.e_entry, self.e_phoff,
         self.e_shoff, self.e_flags, self.e_ehsize, self.e_phentsize, self.e_phnum,
         self.e_shentsize, self.e_shnum, self.e_shstrndx) = struct.unpack_from(self.e+'HHIIIIIHHHHHH', d, 16)
        self.sections=[]
        for i in range(self.e_shnum):
            off=self.e_shoff+i*self.e_shentsize
            (name,typ,flags,addr,offset,size,link,info,align,entsize)=struct.unpack_from(self.e+'10I', d, off)
            self.sections.append(dict(name=name,type=typ,flags=flags,addr=addr,offset=offset,
                                      size=size,link=link,info=info,align=align,entsize=entsize,index=i))
        shstr=self.sections[self.e_shstrndx]
        self.shstrtab=d[shstr['offset']:shstr['offset']+shstr['size']]
        for s in self.sections:
            s['sname']=self.cstr(self.shstrtab, s['name'])
    def cstr(self, tab, off):
        end=tab.find(b'\0',off)
        return tab[off:end].decode('latin1')
    def sec(self, name):
        for s in self.sections:
            if s['sname']==name: return s
        return None
    def secdata(self, s):
        if s['type']==8: return b'\0'*s['size']
        return self.d[s['offset']:s['offset']+s['size']]
    def symbols(self):
        symtab=self.sec('.symtab')
        if symtab is None: return []
        strtab=self.sections[symtab['link']]
        st=self.d[strtab['offset']:strtab['offset']+strtab['size']]
        out=[]
        n=symtab['size']//16
        for i in range(n):
            off=symtab['offset']+i*16
            (nm,value,size,info,other,shndx)=struct.unpack_from(self.e+'IIIBBH', self.d, off)
            out.append(dict(name=self.cstr(st,nm), value=value, size=size,
                            bind=info>>4, type=info&0xf, shndx=shndx, idx=i))
        return out
    def relocs(self, secname):
        # returns list of (offset, symidx, type) for section named secname
        out=[]
        for s in self.sections:
            if s['type']==9 and s['sname']=='.rel'+secname:  # SHT_REL
                data=self.d[s['offset']:s['offset']+s['size']]
                for i in range(0,len(data),8):
                    off,info=struct.unpack_from(self.e+'II',data,i)
                    out.append((off, info>>8, info&0xff))
            elif s['type']==4 and s['sname']=='.rela'+secname:
                data=self.d[s['offset']:s['offset']+s['size']]
                for i in range(0,len(data),12):
                    off,info,add=struct.unpack_from(self.e+'IIi',data,i)
                    out.append((off, info>>8, info&0xff))
        return out
