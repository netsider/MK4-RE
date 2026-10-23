#!/usr/bin/env python3
"""MK4 PC (1998) texture extractor: decodes every RLE-555 texture page in every .GEO inside FILESYS.DAT to PNG,
plus a contact sheet per GEO, and copies MENU.TGA out (MK4_PC_FILE_FORMATS.txt section 3).

Needs: Python 3, Pillow; fsys_tool.py and export_pc_geo.py from this folder.
Usage:
  python extract_textures.py FILESYS.DAT MK4.EXE OUTDIR
Output: OUTDIR/<geo name>/NNN_WxH.png, OUTDIR/<geo name>_sheet.png, OUTDIR/menu.tga (+ menu.png), OUTDIR/report.txt
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
from fsys_tool import entries, candidate_names
from export_pc_geo import decode_rle555


def main(a):
    if len(a) != 3:
        raise SystemExit(__doc__)
    fs = open(a[0], 'rb').read(); names = candidate_names(open(a[1], 'rb').read()); out = a[2]
    os.makedirs(out, exist_ok=True); rep = []
    for i, (h, o, s) in enumerate(entries(fs)):
        d = fs[o:o + s]; base = names.get(h, 'entry_%03d' % i).split('\\')[-1].lower()
        if base.endswith('.tga'):
            open(os.path.join(out, base), 'wb').write(d)
            try:
                Image.open(os.path.join(out, base)).save(os.path.join(out, base[:-4] + '.png'))
                rep.append('%s  TGA copied and converted' % base)
            except Exception as e:
                rep.append('%s  TGA copied, PIL could not decode: %s' % (base, e))
            continue
        if d[:4] != b'0.1v':
            continue
        try:
            texs = decode_rle555(d, struct.unpack_from('<I', d, 4)[0])
        except Exception as e:
            rep.append('%s  decode error %s' % (base, e)); continue
        stem = base.rsplit('.', 1)[0]; dd = os.path.join(out, stem); os.makedirs(dd, exist_ok=True)
        for k, t in enumerate(texs):
            t.save(os.path.join(dd, '%03d_%dx%d.png' % (k, t.width, t.height)))
        if texs:
            cell = 136; cols = 8; rows = (len(texs) + cols - 1) // cols
            sh = Image.new('RGB', (cols * cell, rows * cell + 20), (40, 0, 40)); dr = ImageDraw.Draw(sh)
            dr.text((4, 4), '%s %d textures' % (base, len(texs)), fill=(255, 255, 255))
            for k, t in enumerate(texs):
                tt = t.copy(); tt.thumbnail((128, 116), Image.NEAREST)
                x, y = (k % cols) * cell, 20 + (k // cols) * cell
                sh.paste(tt, (x + 4, y + 2)); dr.text((x + 4, y + 120), '%d %dx%d' % (k, t.width, t.height), fill=(200, 200, 200))
            sh.save(os.path.join(out, stem + '_sheet.png'))
        rep.append('%s  %d textures: %s' % (base, len(texs), ' '.join('%dx%d' % t.size for t in texs)))
    open(os.path.join(out, 'report.txt'), 'w').write('\n'.join(rep) + '\n')
    print('\n'.join(r[:100] for r in rep))


if __name__ == '__main__':
    main(sys.argv[1:])
