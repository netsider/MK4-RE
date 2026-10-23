#!/usr/bin/env python3
"""MK4 PC (1998) ECM movie decoder: M_*.ECM -> PNG frames + WAV sound.  Python 3 + Pillow (frames only).

Format (traced in MK4.EXE: player VA 0x4AFC60, reader thread 0x4AFFC0, frame decoder 0x4BDD50; see
MK4_PC_FILE_FORMATS.txt section 5):
  header 0xE18 bytes: "ECM" 0x02, u32 frame count, then 900 u32 chunk sizes (one chunk per 15 frames, 0 = unused)
  chunk:  "SEC" 0x00 | 0x2B14 bytes IMA ADPCM sound (1 s: 22050 Hz, 16-bit mono, high nibble first, decoder state
          carried from chunk to chunk) | EDL-compressed video block (rest of the chunk)
  EDL:    "EDL" + method byte (low 7 bits: 0 = stored, 1 = LZ + Huffman; bit 7 = big-endian, not used here),
          u32 packed size (incl. this 12-byte header), u32 unpacked size, then the bit stream.
  video block after EDL ("MPC" 0x02): u16 x 256 palette (15-bit RGB 5-5-5) shared by the chunk's 15 frames,
          then 15 x 4800 u16 block codes (80 x 60 blocks of 4x4 pixels = 320x240), then a codebook of 16-byte
          4x4 blocks (palette indices, row-major). Code >= 65000: solid block of colour (code - 65000) & 0xFF;
          otherwise codebook entry [code].
  The game adds a random "soften" pass on solid blocks (pixels swapped with similar-coloured neighbours); this tool
  skips it, so solid areas may look slightly blockier than in game.

Usage:
  python ecm_tool.py M_MIDWAY.ECM info
  python ecm_tool.py M_MIDWAY.ECM frames OUTDIR [first last step]   PNG frames (default all)
  python ecm_tool.py M_MIDWAY.ECM wav OUT.wav                         the sound track
The EDL1 bit-stream layout follows the description published by Zoinkity (QuickBMS "EDL1"); this is an
independent Python implementation checked byte-for-byte against MK4.EXE's own decoder (VA 0x4B07E0).
No game data is included; pass your own file.
"""
import os, struct, sys, wave

HDR = 0xE18
FRAMES_PER_CHUNK = 15
AUDIO_BYTES = 0x2B14
W, H = 320, 240

LEN_BASE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 0xA, 0xC, 0xE, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x28, 0x30, 0x38, 0x40, 0x50,
            0x60, 0x70, 0x80, 0xA0, 0xC0, 0xE0, 0xFF]
LEN_BITS = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]
DST_BASE = [0, 1, 2, 3, 4, 6, 8, 0xC, 0x10, 0x18, 0x20, 0x30, 0x40, 0x60, 0x80, 0xC0, 0x100, 0x180, 0x200, 0x300,
            0x400, 0x600, 0x800, 0xC00, 0x1000, 0x1800, 0x2000, 0x3000, 0x4000, 0x6000]
DST_BITS = [0, 0, 0, 0] + [i // 2 for i in range(2, 28)]


class Bits:
    def __init__(self, data, pos):
        self.d = bytes(data) + bytes(8); self.n = pos * 8
    def get(self, k):
        p = self.n >> 3
        r = (int.from_bytes(self.d[p:p + 4], 'little') >> (self.n & 7)) & ((1 << k) - 1)
        self.n += k; return r


def huff_table(lengths):
    """canonical Huffman, codes assigned by (length, symbol); returns dict (length, code) -> symbol"""
    syms = sorted((l, s) for s, l in enumerate(lengths) if l)
    tab = {}; code = 0; prev = syms[0][0] if syms else 0
    for l, s in syms:
        code <<= (l - prev); prev = l
        tab[(l, code)] = s; code += 1
    return tab


def read_sym(b, tab, maxlen=16):
    code = 0
    for l in range(1, maxlen + 1):
        code = (code << 1) | b.get(1)
        s = tab.get((l, code))
        if s is not None:
            return s
    raise ValueError('bad Huffman code')


def edl_decode(buf):
    if buf[:3] != b'EDL':
        raise ValueError('not EDL')
    method = buf[3] & 0x7F
    packed, size = struct.unpack_from('<II', buf, 4)
    if method == 0:
        return bytes(buf[12:12 + size])
    if method != 1:
        raise ValueError('EDL method %d not supported' % method)
    b = Bits(buf[:packed], 12); out = bytearray(); last = 0; lt = dt = None
    while True:
        if b.get(1):
            for which in (0, 1):
                n = b.get(9)
                if n:
                    ls = []
                    for _ in range(n):
                        if b.get(1):
                            last = b.get(4)
                        ls.append(last)
                    if which == 0: lt = huff_table(ls)
                    else: dt = huff_table(ls)
            while True:
                s = read_sym(b, lt)
                if s < 0x100:
                    out.append(s)
                elif s == 0x100:
                    break
                else:
                    k = s - 0x101
                    num = LEN_BASE[k] + (b.get(LEN_BITS[k]) if LEN_BITS[k] else 0) + 3
                    d = read_sym(b, dt)
                    back = DST_BASE[d] + (b.get(DST_BITS[d]) if DST_BITS[d] else 0) + 1
                    for _ in range(num):
                        out.append(out[-back] if back <= len(out) else 0)
        else:
            n = b.get(15)
            for _ in range(n):
                out.append(b.get(8))
        if b.get(1):
            break
    return bytes(out[:size])


IMA_STEP = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88,
            97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
            724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
            4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
            18500, 20350, 22385, 24623, 27086, 29794, 32767]
IMA_IDX = [-1, -1, -1, -1, 2, 4, 6, 8]


def ima_decode(data, nsamples, state):
    pred, idx = state; out = []
    for byte in data:
        for nib in (byte >> 4, byte & 15):
            if len(out) >= nsamples: break
            st = IMA_STEP[idx]; diff = st >> 3
            if nib & 4: diff += st
            if nib & 2: diff += st >> 1
            if nib & 1: diff += st >> 2
            pred = pred - diff if nib & 8 else pred + diff
            pred = max(-32768, min(32767, pred))
            idx = max(0, min(88, idx + IMA_IDX[nib & 7]))
            out.append(pred)
    return out, (pred, idx)


class ECM:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        if self.d[:4] != b'ECM\x02':
            raise ValueError('not an ECM file')
        self.frames = struct.unpack_from('<I', self.d, 4)[0]
        self.nchunks = (self.frames + FRAMES_PER_CHUNK - 1) // FRAMES_PER_CHUNK
        self.sizes = struct.unpack_from('<%dI' % self.nchunks, self.d, 8)
        self.offs = []; o = HDR
        for s in self.sizes:
            self.offs.append(o); o += s
        self.end = o

    def chunk(self, i):
        return self.d[self.offs[i]:self.offs[i] + self.sizes[i]]

    def video(self, i):
        v = edl_decode(self.chunk(i)[4 + AUDIO_BYTES:])
        if v[:3] != b'MPC':
            raise ValueError('chunk %d: no MPC block' % i)
        return v

    def frame_rgb(self, v, k):
        pal = struct.unpack_from('<256H', v, 4)
        lut = [bytes((((c >> 10) & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, (c & 31) * 255 // 31)) for c in pal]
        codes = struct.unpack_from('<4800H', v, 0x204 + k * 9600)
        cb = 0x204 + FRAMES_PER_CHUNK * 9600
        idx = bytearray(W * H)
        for bi, c in enumerate(codes):
            bx, by = (bi % 80) * 4, (bi // 80) * 4
            if c >= 65000:
                blk = bytes([(c - 65000) & 0xFF]) * 16
            else:
                blk = v[cb + c * 16: cb + c * 16 + 16]
            for r in range(4):
                o = (by + r) * W + bx
                idx[o:o + 4] = blk[r * 4:r * 4 + 4]
        return b''.join(lut[p] for p in idx), idx, pal


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    e = ECM(sys.argv[1]); cmd = sys.argv[2]
    if cmd == 'info':
        print('frames %d, chunks %d (15 frames + 1 s sound each), header+chunks = %d bytes, file %d bytes'
              % (e.frames, e.nchunks, e.end, len(e.d)))
        print('=> %.1f s at 15 frames/s, 320x240, 8-bit palettised (one 15-bit palette per chunk)' % (e.frames / 15))
        for i in range(min(3, e.nchunks)):
            c = e.chunk(i); m = c[4 + AUDIO_BYTES + 3] & 0x7F
            print(' chunk %d: %d bytes, tag %r, EDL method %d, video %d -> %d bytes' % (
                i, len(c), c[:4], m, *struct.unpack_from('<II', c, 4 + AUDIO_BYTES + 4)))
    elif cmd == 'frames':
        from PIL import Image
        out = sys.argv[3]; os.makedirs(out, exist_ok=True)
        first = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        last = int(sys.argv[5]) if len(sys.argv) > 5 else e.frames - 1
        step = int(sys.argv[6]) if len(sys.argv) > 6 else 1
        cur = None; v = None
        for f in range(first, min(last, e.frames - 1) + 1, step):
            ci, k = divmod(f, FRAMES_PER_CHUNK)
            if ci != cur:
                v = e.video(ci); cur = ci
            rgb = e.frame_rgb(v, k)[0]
            Image.frombytes('RGB', (W, H), rgb).save(os.path.join(out, 'frame_%04d.png' % f))
        print('wrote frames %d..%d to %s' % (first, last, out))
    elif cmd == 'wav':
        st = (0, 0); pcm = []
        for i in range(e.nchunks):
            s, st = ima_decode(e.chunk(i)[4:4 + AUDIO_BYTES], 22050, st); pcm += s
        with wave.open(sys.argv[3], 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(struct.pack('<%dh' % len(pcm), *pcm))
        print('wrote %d samples (%.1f s) to %s' % (len(pcm), len(pcm) / 22050, sys.argv[3]))
    else:
        print(__doc__); sys.exit(1)


if __name__ == '__main__':
    main()
