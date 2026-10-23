#!/usr/bin/env python3
"""MK4 PC (1998) .GEO inspector: block table, 2D sprite records and texture pages (MK4_PC_FILE_FORMATS.txt
section 3). Text/CSV only: it documents where each sprite sits in the texture pages; it does not cut or write
any images.

Needs: Python 3.8+, standard library only (uses fsys_tool.py from this folder to find files by name).

Usage:
  python geo_info.py SRC summary  [GEO ...|ALL] [--exe MK4.EXE]
                                                header, record counts by type, texture pages
                                                (--exe names the entries when listing ALL)
  python geo_info.py SRC blocks   GEO           every 16-byte block record (3D parts and 2D sprite records)
  python geo_info.py SRC sprites  GEO [--csv OUT.csv] [--alpha]
                                                decoded 2D sprite records; --alpha adds the share of transparent
                                                texels (value 0x0000) inside each rectangle
  python geo_info.py SRC pages    GEO           texture pages: size, packed size, transparent-texel share
  SRC is FILESYS.DAT (GEO = disc name such as SHARED_G.GEO, or ALL for every GEO in summary) or a single
  extracted .geo file (then omit GEO).
Record layout (PROVEN, draw code VA 0x4BA01D / 0x4BB180):
  3D part   {u16 type, u16 tri count, s32 vtx rel, s32 strip rel, s32 uv rel}
  2D sprite {u8 flags (0x80 sprite, 0x01 draw next too), u8 blend (&3: 0 opaque, 1/2 additive, 3 50/50),
             u8 page, u8 id, s16 w, s16 h, s16 x, s16 y (on screen), u8 u, u8 v, u8 tw, u8 th (texels)}
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsys_tool import fsys_hash, N_ENTRIES, candidate_names   # noqa: E402

GEO_PREFIX = 'C:\\SOURCE\\MK4\\WIN\\GEOGFX\\'
BLEND = {0: 'opaque', 1: 'additive', 2: 'additive', 3: 'half'}


def load(src, name):
    d = open(src, 'rb').read()
    if d[:4] == b'0.1v':
        return d
    h = fsys_hash(GEO_PREFIX + name)
    for i in range(N_ENTRIES):
        hh, off, size = struct.unpack_from('<III', d, i * 12)
        if hh == h:
            return d[off:off + size]
    raise SystemExit('not found in %s: %s' % (src, name))


def all_geos(src):
    d = open(src, 'rb').read()
    out = []
    for i in range(N_ENTRIES):
        hh, off, size = struct.unpack_from('<III', d, i * 12)
        if d[off:off + 4] == b'0.1v':
            out.append((i, hh, d[off:off + size]))
    return out


def records(g):
    """Walk the block table. Returns (tex_off, list of dicts). Stops at tex_off, at the first byte any 3D part
    points to, or at a 3D record that fails the strip/UV checks."""
    tex_off = struct.unpack_from('<I', g, 4)[0]
    lim = tex_off; o = 0x0C; out = []
    while o + 16 <= lim:
        b0 = g[o]
        if b0 & 0x80:
            blend, page, rid = g[o + 1] & 3, g[o + 2], g[o + 3]
            w, h, x, y = struct.unpack_from('<4h', g, o + 4)
            u, v, tw, th = g[o + 12:o + 16]
            out.append(dict(off=o, kind='sprite', flags=b0, blend=blend, blend_raw=g[o + 1], page=page, id=rid,
                            w=w, h=h, x=x, y=y, u=u, v=v, tw=tw, th=th))
            o += 16; continue
        typ, cnt, a, b, c = struct.unpack_from('<HHiii', g, o)
        if cnt == 0:
            break
        vtx, strip, uv = o + 4 + a, o + 8 + b, o + 12 + c
        if not (0 < strip < tex_off and 0 < vtx < tex_off):
            break
        s = strip; total = 0; nvert = 0
        while s + 4 <= len(g):
            fl, n = struct.unpack_from('<Hh', g, s); s += 4
            if n < 0:
                break
            total += n + 1; nvert += n + 3
        if total != cnt or vtx + 12 * nvert != uv:
            break
        out.append(dict(off=o, kind='part', type=typ, count=cnt, nvert=nvert, vtx_off=vtx, strip_off=strip, uv_off=uv))
        lim = min(lim, vtx, strip, uv)
        o += 16
    return tex_off, out


def pages(g, tex_off, decode=False):
    p = tex_off + 4
    count = struct.unpack_from('<I', g, p)[0]; p += 4
    out = []
    for _ in range(count):
        w, h, packed = struct.unpack_from('<HHI', g, p); p += 8
        pix = None
        if decode:
            pix = []; q = p; end = p + packed
            for _row in range(h):                    # same row rule as export_pc_geo.decode_rle555
                row = []
                while len(row) < w and q + 1 < end:
                    t = g[q] | (g[q + 1] << 8); q += 2
                    if t & 0x8000:
                        run = g[q] if q < end else 0; q += 1
                        row.extend([t & 0x7FFF] * run)
                    else:
                        row.append(t)
                row = row[:w]; row.extend([0] * (w - len(row))); pix.extend(row)
        out.append(dict(w=w, h=h, packed=packed, pix=pix))
        p += packed
    return out


def transparent_share(pg, u, v, tw, th):
    if pg is None or pg['pix'] is None or tw == 0 or th == 0:
        return None
    W, H, P = pg['w'], pg['h'], pg['pix']; z = n = 0
    for yy in range(v, min(v + th, H)):
        row = yy * W
        for xx in range(u, min(u + tw, W)):
            n += 1; z += P[row + xx] == 0
    return z / n if n else None


def type_name(r):
    if r['kind'] == 'sprite':
        return 'sprite%s' % ('+next' if r['flags'] & 1 else '')
    t = r['type']; b0 = t & 0xFF
    if b0 & 0x40: return '3D unlit (0x40)'
    if b0 & 0x02: return '3D depth-shaded (0x2)'
    if t == 1: return '3D type 1 (fighter parts)'
    if t == 0x100: return '3D (0x100, draws as 0)'
    return '3D lit (0x%X)' % t


def summary(name, g):
    tex_off, rs = records(g); pg = pages(g, tex_off)
    kinds = {}
    for r in rs:
        k = type_name(r); kinds[k] = kinds.get(k, 0) + 1
    print('%-14s size %7d  tex_off 0x%06X  records %3d  %s' % (name, len(g), tex_off, len(rs),
          ', '.join('%s x%d' % kv for kv in sorted(kinds.items()))))
    print('%-14s pages %d: %s' % ('', len(pg), ' '.join('%dx%d' % (p['w'], p['h']) for p in pg)))


def main(a):
    if len(a) < 2 or a[0] in ('-h', '--help'):
        raise SystemExit(__doc__)
    src, cmd, rest = a[0], a[1], a[2:]
    opts = [x for x in rest if x.startswith('--')]
    csv_out = None; exe = None
    if '--exe' in rest:
        i = rest.index('--exe'); exe = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
    if '--csv' in rest:
        i = rest.index('--csv'); csv_out = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
    names = [x for x in rest if not x.startswith('--')]
    single = open(src, 'rb').read(4) == b'0.1v'
    if cmd == 'summary':
        if single:
            summary(os.path.basename(src), load(src, None)); return
        if names == ['ALL'] or not names:
            nm = candidate_names(open(exe, 'rb').read()) if exe else {}
            for i, hh, g in all_geos(src):
                summary(nm[hh].split('\\')[-1] if hh in nm else 'entry %d' % i, g)
            return
        for n in names:
            summary(n, load(src, n))
        return
    if not single and not names:
        raise SystemExit('name a GEO, e.g. SHARED_G.GEO')
    g = load(src, names[0] if names else None)
    tex_off, rs = records(g)
    if cmd == 'blocks':
        for k, r in enumerate(rs):
            if r['kind'] == 'part':
                print('%3d  0x%05X  %-24s tris %4d verts %4d  vtx 0x%05X strips 0x%05X uv 0x%05X' % (
                    k, r['off'], type_name(r), r['count'], r['nvert'], r['vtx_off'], r['strip_off'], r['uv_off']))
            else:
                print('%3d  0x%05X  %-24s page %d id %d' % (k, r['off'], type_name(r), r['page'], r['id']))
    elif cmd == 'sprites':
        pg = pages(g, tex_off, decode='--alpha' in opts)
        cols = ['rec', 'offset', 'flags', 'blend', 'page', 'id', 'screen_w', 'screen_h', 'screen_x', 'screen_y',
                'u', 'v', 'tex_w', 'tex_h', 'in_page'] + (['transparent'] if '--alpha' in opts else [])
        rows = []
        for k, r in enumerate(rs):
            if r['kind'] != 'sprite':
                continue
            p = pg[r['page']] if r['page'] < len(pg) else None
            inside = p is not None and r['u'] + r['tw'] <= p['w'] and r['v'] + r['th'] <= p['h']
            row = [k, '0x%05X' % r['off'], '0x%02X' % r['flags'], BLEND[r['blend']], r['page'], r['id'],
                   r['w'], r['h'], r['x'], r['y'], r['u'], r['v'], r['tw'], r['th'], 'yes' if inside else 'NO']
            if '--alpha' in opts:
                t = transparent_share(p, r['u'], r['v'], r['tw'], r['th'])
                row.append('' if t is None else '%.3f' % t)
            rows.append(row)
        if csv_out:
            with open(csv_out, 'w') as f:
                f.write(','.join(cols) + '\n')
                for row in rows:
                    f.write(','.join(map(str, row)) + '\n')
            print('wrote %d sprite records to %s' % (len(rows), csv_out))
        else:
            print(' '.join(cols))
            for row in rows:
                print(' '.join(map(str, row)))
    elif cmd == 'pages':
        for k, p in enumerate(pages(g, tex_off, decode=True)):
            z = sum(1 for c in p['pix'] if c == 0)
            print('page %d  %dx%d  packed %d bytes  transparent texels %.3f' % (k, p['w'], p['h'], p['packed'],
                  z / max(1, len(p['pix']))))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
