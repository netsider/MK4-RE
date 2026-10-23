#!/usr/bin/env python3
"""MK4 PC (1998) animation frame decoder in pure Python (no emulator): a re-implementation of MK4.EXE's frame
decompressor (VA 0x4013A0) (MK4_PC_FILE_FORMATS.txt sections 5-6). Use tools\\anim_emu.py when you want the
game's own code to do the work; this tool gives the same words without numpy/unicorn.

Needs: Python 3.8+, standard library only.
Inputs: MK4.EXE (the 1,182,720-byte build) plus ANIMDAT4.AP0 / ANIMDAT4.AP1 extracted from FILESYS.DAT
        (tools\\fsys_tool.py extract ...).

Usage:
  python anim_decode.py DIR info                  one line per clip: id, C(ompressed)/U, size, frames, nodes, and
                                                  'flag0x1' for the 27 clips with bit 0 of descriptor +0x8 set
                                                  (meaning unknown)
  python anim_decode.py DIR dump CLIP [OUT.csv]   per-frame words for one clip (frame, node0..nodeN-1), hex
  python anim_decode.py DIR verify [CLIPS...]     compare against anim_emu.py (needs numpy + unicorn); default =
                                                  every compressed clip. Result on the retail files: 32,972 frames
                                                  in 571 compressed clips, 0 mismatches.
  DIR holds MK4.EXE, ANIMDAT4.AP0 and ANIMDAT4.AP1.
Frame words: words 0-2 = root translation (signed 32-bit; /65536 = game units), then one packed word per bone
  (three 11-bit angle fields, see the guide).
As a module:  A = AnimDecoder(DIR); A.clip(k) -> list of frames (lists of u32); A.decode(k, frame) -> list.
"""
import os, struct, sys

CLIP_TABLE_FILE_OFF = 0xFC76C          # VA 0x4FDD6C, 12-byte records {data ptr, frames, nodes<<16 | flags}


def _s8(x):
    return x - 256 if x & 0x80 else x


class _Bits:
    """LSB-first bit reader over 32-bit little-endian words, as in the game's decompressor."""
    def __init__(self, data, pos):
        self.d = data; self.pos = pos; self.bits = 32; self.buf = 0

    def pull(self):
        w = struct.unpack_from('<I', self.d, self.pos)[0] if self.pos + 4 <= len(self.d) else 0
        self.pos += 4
        return w

    def read(self, n):
        mask = (1 << n) - 1; had = self.bits; self.bits -= n
        if self.bits < 0:
            nw = self.pull(); out = ((nw << had) + self.buf) & mask
            self.buf = nw >> (-self.bits); self.bits += 32
        else:
            out = self.buf & mask; self.buf >>= n
        return out

    def peek(self, n):
        if self.bits >= n:
            return self.buf & ((1 << n) - 1)
        nxt = struct.unpack_from('<I', self.d, self.pos)[0] if self.pos + 4 <= len(self.d) else 0
        return (self.buf + (nxt << self.bits)) & ((1 << n) - 1)

    def seek(self, delta):
        p = self.pos * 8 - self.bits + delta; frac = p & 31
        self.pos = (p >> 3) & ~3; self.bits = 32 - frac; self.buf = self.pull() >> frac


class AnimDecoder:
    def __init__(self, d):
        e = open(os.path.join(d, 'MK4.EXE'), 'rb').read()
        a = open(os.path.join(d, 'ANIMDAT4.AP0'), 'rb').read()
        self.ap1 = open(os.path.join(d, 'ANIMDAT4.AP1'), 'rb').read()
        if len(e) != 1182720:
            print('warning: MK4.EXE is not the 1,182,720-byte build these addresses were taken from', file=sys.stderr)
        self.nib = struct.unpack_from('<256H', a, 0)      # AP0 +0x000: 256-entry code table
        self.ents = {}; p = 0x200; o = 0
        while True:
            r, s = struct.unpack_from('<HH', a, p); p += 4
            if r == 0xFFFF:
                break
            i = r & 0x7FFF
            _, fr, w = struct.unpack_from('<iiI', e, CLIP_TABLE_FILE_OFF + i * 12)
            self.ents[i] = dict(comp=bool(r & 0x8000), size=s, off=o, frames=fr, nodes=w >> 16, flag1=w & 1); o += s

    def decode(self, cid, frame):
        E = self.ents[cid]
        if not E['comp']:
            n = E['nodes']; return list(struct.unpack_from('<%dI' % n, self.ap1, E['off'] + 4 * n * frame))
        nb = E['nodes'] - 3; flim = E['frames']; b = _Bits(self.ap1, E['off'])
        hdr = [b.pull() for _ in range(6)]; b.buf = b.pull(); b.bits = 32
        skip = frame
        while True:                                   # 16-frame blocks: skip whole blocks
            dd = b.read(13)
            if skip < 0x10:
                break
            skip -= 0x10; b.seek(dd)
        n3 = nb * 3
        keyed = [0] * n3; delta = [0] * n3; span = [0] * n3; nib = [0] * n3; extra = [0] * n3
        for i in range(n3):
            k = i % 3; f = b.read(1); sh = k >> 1; v = b.read(11 - sh) << sh
            if v & 0x400:
                v -= 0x800
            keyed[i] = f; delta[i] = v
            if f:
                span[i] = b.read(8)
        if skip > 7:
            rep = skip - 7
        else:
            lim = 7; last = flim - 1
            if frame >= (last & ~15):
                lim = min(lim, last & 15)
            rep = lim - skip
        s0, s1, s2 = b.read(8), b.read(8), b.read(8)
        for i in range(n3):
            if not keyed[i]:
                continue
            n4 = b.read(4); nib[i] = n4
            if n4:
                continue
            if rep == 0:
                extra[i] = b.read(8)
            else:
                b.read(8)
        dd = b.read(12)
        if skip > 7:
            b.seek(dd)
        while rep > 0:
            rep -= 1
            if rep == 0:
                s0, s1, s2 = b.read(8), b.read(8), b.read(8)
            else:
                b.read(24)
            for i in range(n3):
                if not keyed[i]:
                    continue
                ent = self.nib[b.peek(8)]; used = ent & 15; add = ent >> 7
                if used:
                    b.read(used)
                nib[i] = (nib[i] + add) & 15
                if nib[i]:
                    continue
                if rep == 0:
                    extra[i] = b.read(8)
                else:
                    b.read(8)
        out = [((s0 * hdr[0]) >> 8) + hdr[1], ((s1 * hdr[2]) >> 8) + hdr[3], ((s2 * hdr[4]) >> 8) + hdr[5]]
        for bi in range(nb):
            pk = 0; shf = 0
            for k in range(3):
                i = bi * 3 + k
                if not keyed[i]:
                    v = delta[i]
                elif nib[i] == 0:
                    v = _s8(extra[i]) << 3
                else:
                    v = span[i] * (nib[i] - 1) + delta[i]
                v &= 0x7FF; v >>= (k >> 1); pk += v << shf; shf += 11
            out.append(pk)
        return [x & 0xFFFFFFFF for x in out]

    def clip(self, cid):
        return [self.decode(cid, f) for f in range(self.ents[cid]['frames'])]


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ('-h', '--help'):
        print(__doc__); return
    A = AnimDecoder(sys.argv[1]); cmd = sys.argv[2]
    if cmd == 'info':
        for k, E in sorted(A.ents.items()):
            print('%3d  %s  size %6d  frames %4d  nodes %3d%s' % (k, 'C' if E['comp'] else 'U', E['size'], E['frames'],
                  E['nodes'], '  flag0x1' if E['flag1'] else ''))
    elif cmd == 'dump':
        k = int(sys.argv[3], 0); rows = A.clip(k)
        lines = ['%d,%s' % (f, ','.join('%08X' % w for w in r)) for f, r in enumerate(rows)]
        if len(sys.argv) > 4:
            open(sys.argv[4], 'w').write('\n'.join(lines) + '\n'); print('wrote', len(rows), 'frames')
        else:
            print('\n'.join(lines))
    elif cmd == 'verify':
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from anim_emu import Anim
        E = Anim(sys.argv[1])
        ids = [int(x, 0) for x in sys.argv[3:]] or sorted(k for k, v in A.ents.items() if v['comp'])
        bad = 0; n = 0
        for k in ids:
            for f in range(A.ents[k]['frames']):
                n += 1
                if A.decode(k, f) != list(E.decode(k, f)):
                    bad += 1; print('MISMATCH clip', k, 'frame', f)
        print('checked %d frames in %d clips, %d mismatches' % (n, len(ids), bad))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
