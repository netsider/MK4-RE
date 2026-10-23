#!/usr/bin/env python3
"""MK4 PC (1998) FILESYS.DAT load map: which entries did the game actually read? Parses strace logs of the game
(Linux/Wine) and maps every read of FILESYS.DAT back to directory entries and their names
(MK4_PC_FILE_FORMATS.txt sections 1-2: the same kind of strace mapping found the .geo files a live session loads).

Record the log with fd paths shown, for example:
  strace -f -y -e trace=read,pread64,lseek,_llseek -o fs.log wine MK4.EXE
Needs: Python 3.8+, standard library only (uses fsys_tool.py from this folder for the names).

Usage:
  python fsys_strace_map.py FILESYS.DAT MK4.EXE LOG [LOG ...] [--csv OUT.csv]
Output: one line per entry touched: index, name, entry size, bytes read (summed over all logs).
"""
import os, re, struct, sys, bisect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsys_tool import entries, candidate_names   # noqa: E402

RX = re.compile(r'^(?:\[pid\s+)?(\d+)\]?\s+(pread64|read|_llseek|lseek)\((\d+)<[^>]*filesys\.dat>,\s*(.*)$', re.I)


def parse(fn, starts, ents, hits):
    pos = {}
    for line in open(fn, errors='replace'):
        m = RX.match(line.rstrip())
        if not m:
            continue
        _tid, call, fd, rest = m.groups()
        if call in ('_llseek', 'lseek'):
            mm = re.search(r'\[(\d+)\]', rest) if call == '_llseek' else re.search(r'=\s*(\d+)$', rest)
            if mm:
                pos[fd] = int(mm.group(1))
            continue
        r = re.search(r'=\s*(\d+)$', rest)
        if not r:
            continue
        n = int(r.group(1))
        if call == 'pread64':
            mo = re.search(r',\s*(\d+)\)\s*=\s*\d+$', rest)
            if not mo:
                continue
            off = int(mo.group(1))
        else:
            off = pos.get(fd, 0); pos[fd] = off + n
        if n == 0:
            continue
        k = max(0, bisect.bisect_right(starts, off) - 1)
        while k < len(ents) and ents[k][0] < off + n:
            o, s, i = ents[k]
            if o + s > off:
                hits[i] = hits.get(i, 0) + min(o + s, off + n) - max(o, off)
            k += 1


def main(a):
    if len(a) < 3 or a[0] in ('-h', '--help'):
        raise SystemExit(__doc__)
    csv_out = None
    if '--csv' in a:
        i = a.index('--csv'); csv_out = a[i + 1]; a = a[:i] + a[i + 2:]
    fs = open(a[0], 'rb').read(799 * 12)
    names = candidate_names(open(a[1], 'rb').read())
    dirs = entries(fs)
    ents = sorted((off, size, i) for i, (h, off, size) in enumerate(dirs))
    starts = [e[0] for e in ents]
    hits = {}
    for fn in a[2:]:
        parse(fn, starts, ents, hits)
        print('# %s: %d entries touched so far' % (fn, len(hits)), file=sys.stderr)
    rows = []
    for i in sorted(hits):
        h, off, size = dirs[i]
        rows.append((i, names.get(h, '?').split('\\')[-1], size, hits[i]))
    if csv_out:
        with open(csv_out, 'w') as f:
            f.write('index,name,size,bytes_read\n')
            for r in rows:
                f.write('%d,%s,%d,%d\n' % r)
        print('wrote %d entries to %s' % (len(rows), csv_out))
    else:
        for r in rows:
            print('%3d  %-16s size %8d  read %8d' % r)
        print('%d entries, %d .geo' % (len(rows), sum(1 for r in rows if r[1].lower().endswith('.geo'))))


if __name__ == '__main__':
    main(sys.argv[1:])
