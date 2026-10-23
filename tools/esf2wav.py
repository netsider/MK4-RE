#!/usr/bin/env python3
"""MK4 PC (1998) ESF sound -> WAV converter.  Python 3 standard library only.

ESF layout (MK4_PC_FILE_FORMATS.txt section 4): "ESF" 0x06, u32 (low 24 bits = length, top byte = flags), data.
  flags 0x20 = 4-bit IMA ADPCM, high nibble first (decodes to 16-bit PCM); else 8-bit unsigned PCM
  flags 0x40 = 22050 Hz, else 11025 Hz; mono.

Usage:
  python esf2wav.py FILESYS.DAT OUTDIR          convert every ESF in the container (named pcmkNNNN.wav when the
                                                 name hash matches c:\\source\\mk4\\win\\sound\\pcmkNNNN.esf)
  python esf2wav.py --file SOUND.ESF OUT.WAV    convert one extracted ESF file
"""
import os, struct, sys, wave

IDX = [-1, -1, -1, -1, 2, 4, 6, 8] * 2
STEP = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97,
        107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
        876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428,
        4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350,
        22385, 24623, 27086, 29794, 32767]


def fsys_hash(path):
    s = path.upper(); h = 0; shift = 0
    for ch in s:
        b = ord(ch)
        if b >= 0x80: b -= 0x100
        h = (h + (b << shift)) & 0xFFFFFFFF
        shift = shift + 8 if shift < 24 else 0
    return (h + len(s)) & 0xFFFFFFFF


def ima_decode(data):
    """IMA ADPCM, high nibble first, predictor and index start at 0."""
    p = 0; si = 0; out = bytearray()
    for byte in data:
        for nib in (byte >> 4, byte & 15):
            st = STEP[si]; d = st >> 3
            if nib & 4: d += st
            if nib & 2: d += st >> 1
            if nib & 1: d += st >> 2
            p = p - d if nib & 8 else p + d
            p = max(-32768, min(32767, p))
            si = max(0, min(88, si + IDX[nib]))
            out += struct.pack('<h', p)
    return bytes(out)


def esf_to_wav(d, fn):
    if d[:3] != b'ESF':
        raise ValueError('not an ESF file')
    v = struct.unpack_from('<I', d, 4)[0]; flags = v >> 24; length = v & 0xFFFFFF
    rate = 22050 if flags & 0x40 else 11025
    if flags & 0x20:
        pcm = ima_decode(d[8:]); width = 2
    else:
        pcm = d[8:8 + length]; width = 1
    with wave.open(fn, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(width); w.setframerate(rate); w.writeframes(pcm)
    return rate, width, flags


def main(a):
    if len(a) == 3 and a[0] == '--file':
        print(a[2], esf_to_wav(open(a[1], 'rb').read(), a[2])); return
    if len(a) != 2:
        raise SystemExit(__doc__)
    fs = open(a[0], 'rb').read(); out = a[1]; os.makedirs(out, exist_ok=True)
    names = {fsys_hash('c:\\source\\mk4\\win\\sound\\pcmk%04d.esf' % n): n for n in range(10000)}
    count = 0
    for i in range(799):
        h, off, size = struct.unpack_from('<III', fs, i * 12)
        d = fs[off:off + size]
        if d[:3] != b'ESF':
            continue
        n = names.get(h)
        fn = os.path.join(out, ('pcmk%04d.wav' % n) if n is not None else ('entry_%03d.wav' % i))
        esf_to_wav(d, fn); count += 1
    print('wrote', count, 'WAV files to', out)


if __name__ == '__main__':
    main(sys.argv[1:])
