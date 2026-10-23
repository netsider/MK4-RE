#!/usr/bin/env python3
"""MK4 PC (1998) FILESYS.DAT lister / extractor.  Python 3 standard library only.

FILESYS.DAT starts with 799 directory entries {u32 hash, u32 offset, u32 size}; there are no names in the
container. Names are recovered by hashing candidate paths built from strings in MK4.EXE (see
MK4_PC_FILE_FORMATS.txt sections 1-2).

Usage:
  python fsys_tool.py FILESYS.DAT MK4.EXE list              table: index, offset, size, magic, recovered name
  python fsys_tool.py FILESYS.DAT MK4.EXE extract OUTDIR    write every entry (named ones by name, others as entry_NNN.bin)
  python fsys_tool.py FILESYS.DAT - hash "C:\\SOURCE\\MK4\\WIN\\GEOGFX\\SZ_GEO.GEO"   print the hash of one path
"""
import os, re, struct, sys

N_ENTRIES = 799
PREFIXES = ['C:\\SOURCE\\MK4\\WIN\\GEOGFX\\', 'C:\\SOURCE\\MK4\\WIN\\ANIM\\', 'C:\\SOURCE\\MK4\\WIN\\', '']


def fsys_hash(path):
    s = path.upper()
    h = 0; shift = 0
    for ch in s:
        b = ord(ch)
        if b >= 0x80:
            b -= 0x100                      # signed char
        h = (h + (b << shift)) & 0xFFFFFFFF
        shift = shift + 8 if shift < 24 else 0
    return (h + len(s)) & 0xFFFFFFFF


def entries(fs):
    return [struct.unpack_from('<III', fs, i * 12) for i in range(N_ENTRIES)]


def candidate_names(exe):
    cand = set()
    for m in re.finditer(rb'[A-Za-z0-9_\\:.]{4,80}', exe):
        s = m.group().decode('ascii')
        base = s.split('\\')[-1]
        for p in PREFIXES:
            cand.add(p + base); cand.add(p + s)
    for ext in ('AP0', 'AP1'):
        cand.add('C:\\SOURCE\\MK4\\WIN\\ANIM\\ANIMDAT4.' + ext)
    for n in range(10000):                   # sounds: c:\source\mk4\win\sound\pcmkNNNN.esf
        cand.add('c:\\source\\mk4\\win\\sound\\pcmk%04d.esf' % n)
    return {fsys_hash(c): c for c in cand}


def magic(d):
    if d[:3] == b'ESF': return 'ESF'
    if d[:4] == b'0.1v': return 'GEO'
    return d[:4].hex()


def main(a):
    if len(a) >= 3 and a[2] == 'hash':
        print('0x%08X' % fsys_hash(a[3])); return
    if len(a) < 3:
        raise SystemExit(__doc__)
    fs = open(a[0], 'rb').read()
    names = candidate_names(open(a[1], 'rb').read())
    ents = entries(fs)
    if a[2] == 'list':
        named = 0
        for i, (h, off, size) in enumerate(ents):
            n = names.get(h, '')
            named += bool(n)
            print('%3d  0x%08X  off %10d  size %9d  %-8s %s' % (i, h, off, size, magic(fs[off:off + 8]), n))
        print('# %d of %d entries named' % (named, len(ents)))
    elif a[2] == 'extract':
        out = a[3]; os.makedirs(out, exist_ok=True)
        for i, (h, off, size) in enumerate(ents):
            n = names.get(h)
            fn = n.replace('/', '\\').split('\\')[-1] if n else 'entry_%03d.bin' % i
            with open(os.path.join(out, fn), 'wb') as f:
                f.write(fs[off:off + size])
        print('wrote', len(ents), 'files to', out)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
