#!/usr/bin/env python3
"""MK4 PC (1998) clip cross-reference: where does MK4.EXE refer to a clip? Lists every place the clip's descriptor
record (VA 0x4FDD6C + 12 * clip) is used:
  code  a 32-bit immediate in .text equal to the record address (e.g. "push 0x4FEB28" / "mov reg, 0x4FEB28")
  (code is a byte-wise scan of .text, so a match inside unrelated instruction bytes is possible but rare)
  fix   a slot patched at start-up from the fix-up lists 0x4D6E80 / 0x4DC3F8 ({dest, value} pairs,
        *dest |= value >> 2); this is how fighter scripts get their clip operands (MK4_PC_FILE_FORMATS.txt 8A)
Feed a 'fix' address to script_decoder_v3.py (dis / script) to read the script around it.

Needs: Python 3.8+, standard library only (uses script_decoder_v3.py from this folder). Reads the EXE read-only.

Usage:
  python clip_refs.py MK4.EXE CLIP [CLIP ...]     references for the given clips
  python clip_refs.py MK4.EXE all [--unused]      one line per clip 0-611 with counts (--unused: only clips with
                                                  no code or fix reference)
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from script_decoder_v3 import MK4, CLIP_TAB, CLIP_REC   # noqa: E402

NCLIPS = 612


def build(m):
    code = {}; fix = {}
    for o in range(0, len(m.code) - 3):
        v = struct.unpack_from('<I', m.code, o)[0]
        if CLIP_TAB <= v < CLIP_TAB + CLIP_REC * NCLIPS and (v - CLIP_TAB) % CLIP_REC == 0:
            code.setdefault((v - CLIP_TAB) // CLIP_REC, []).append(m.t0 + o)
    for dst, vs in m.FX.items():
        for v in vs:
            if CLIP_TAB <= v < CLIP_TAB + CLIP_REC * NCLIPS and (v - CLIP_TAB) % CLIP_REC == 0:
                fix.setdefault((v - CLIP_TAB) // CLIP_REC, []).append(dst)
    return code, fix


def main(a):
    if len(a) < 2 or a[0] in ('-h', '--help'):
        raise SystemExit(__doc__)
    m = MK4(a[0]); code, fix = build(m)
    if a[1] == 'all':
        for c in range(NCLIPS):
            nc, nf = len(code.get(c, [])), len(fix.get(c, []))
            if '--unused' in a and (nc or nf):
                continue
            print('clip %3d  record 0x%06X  code %3d  fix %3d' % (c, CLIP_TAB + CLIP_REC * c, nc, nf))
        return
    for c in map(lambda s: int(s, 0), a[1:]):
        print('clip %d  record 0x%06X' % (c, CLIP_TAB + CLIP_REC * c))
        print('  code: ' + (' '.join('0x%06X' % x for x in sorted(code.get(c, []))) or '-'))
        print('  fix:  ' + (' '.join('0x%06X' % x for x in sorted(fix.get(c, []))) or '-'))


if __name__ == '__main__':
    main(sys.argv[1:])
