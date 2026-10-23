#!/usr/bin/env python3
"""MK4 PC (1998) animation frame decoder: runs MK4.EXE's own decompressor (VA 0x4013A0) under the Unicorn CPU
emulator, so the output is exactly what the game computes (MK4_PC_FILE_FORMATS.txt sections 5-6).

Needs: Python 3, numpy, unicorn (pip install unicorn numpy).
Inputs: MK4.EXE (the 1,182,720-byte build) plus ANIMDAT4.AP0 / ANIMDAT4.AP1 extracted from FILESYS.DAT
        (tools\\fsys_tool.py extract ...).

Usage:
  python anim_emu.py DIR info                 one line per clip: id, compressed, size, frames, nodes
  python anim_emu.py DIR dump CLIP [OUT.csv]  raw per-frame words for one clip (frame, node0..nodeN-1), hex
  DIR holds MK4.EXE, ANIMDAT4.AP0 and ANIMDAT4.AP1.
As a module:  A = Anim(DIR); A.clip(k) -> numpy array [frames, nodes] of u32 words; A.decode(k, frame) -> list.
"""
import os, struct, sys
import numpy as np
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP

RET = 0xDEAD0000
OUT = 0x521AD8


class Anim:
    def __init__(self, d):
        e = open(os.path.join(d, 'MK4.EXE'), 'rb').read()
        a = open(os.path.join(d, 'ANIMDAT4.AP0'), 'rb').read()
        self.ap1 = open(os.path.join(d, 'ANIMDAT4.AP1'), 'rb').read()
        if len(e) != 1182720:
            print('warning: MK4.EXE is not the 1,182,720-byte build these addresses were taken from', file=sys.stderr)
        self.ents = {}; p = 0x200; o = 0
        while True:
            r, s = struct.unpack_from('<HH', a, p); p += 4
            if r == 0xFFFF:
                break
            i = r & 0x7FFF
            z, fr, w = struct.unpack_from('<iiI', e, 0xFC76C + i * 12)
            self.ents[i] = dict(comp=bool(r & 0x8000), size=s, off=o, frames=fr, nodes=w >> 16); o += s
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(0x400000, 0xC00000)
        uc.mem_write(0x401000, e[0x400:0x400 + 0xCF000])
        uc.mem_write(0x4D0000, e[0xCF400:0xCF400 + 0x2600])
        uc.mem_write(0x4D3000, e[0xD1A00:0xD1A00 + 0x4EC00])
        uc.mem_write(0x5220D8, a[:0x200])                  # the 512-byte decode table from AP0
        self.db = 0x2000000
        uc.mem_map(self.db, (len(self.ap1) + 0x10000 + 0xFFF) & ~0xFFF); uc.mem_write(self.db, self.ap1)
        self.st = 0x3000000; uc.mem_map(self.st, 0x100000)
        uc.mem_map(RET, 0x1000)

    def _w32(self, va, v):
        self.uc.mem_write(va, struct.pack('<I', v & 0xFFFFFFFF))

    def decode(self, cid, frame):
        E = self.ents[cid]
        self._w32(0x521A64, self.db + E['off']); self._w32(0x521AA4, E['frames'])
        self._w32(0x521AA0, E['nodes'] - 3); self._w32(0x521A60, frame); self._w32(0x521A9C, OUT)
        self.uc.mem_write(0x521A98, b'\0')
        sp = self.st + 0x80000; self._w32(sp, RET); self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.emu_start(0x4013A0, RET, count=2000000)
        return list(struct.unpack('<%dI' % E['nodes'], self.uc.mem_read(OUT, 4 * E['nodes'])))

    def clip(self, cid):
        E = self.ents[cid]
        if not E['comp']:
            return np.frombuffer(self.ap1[E['off']:E['off'] + E['size']], dtype='<u4').reshape(-1, E['nodes']).astype(np.uint64)
        return np.array([self.decode(cid, f) for f in range(E['frames'])], dtype=np.uint64)


def main(a):
    if len(a) < 2:
        raise SystemExit(__doc__)
    A = Anim(a[0])
    if a[1] == 'info':
        for k in sorted(A.ents):
            E = A.ents[k]
            print('%3d  %s  size %6d  frames %4d  nodes %3d' % (k, 'C' if E['comp'] else 'U', E['size'], E['frames'], E['nodes']))
    elif a[1] == 'dump':
        k = int(a[2], 0); F = A.clip(k)
        out = open(a[3], 'w') if len(a) > 3 else sys.stdout
        for f, row in enumerate(F):
            out.write('%d,%s\n' % (f, ','.join('%08X' % int(x) for x in row)))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
