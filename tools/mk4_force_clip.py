#!/usr/bin/env python3
"""MK4 PC (1998) forced clip playback: WRITES game memory. Repeatedly stores a clip record (>>2) into a player's
animation struct so the fighter plays that clip; optional --frame also pins the frame index and frame pointer to freeze
one exact frame (MK4_PC_FILE_FORMATS.txt section 9). For capture/inspection on your own running copy only.

Windows (OpenProcess + WriteProcessMemory) or Linux/Wine (/proc/<pid>/mem opened read-write; needs ptrace permission).
Python 3 standard library only. Addresses are for the 1,182,720-byte MK4.EXE.

Usage:
  python mk4_force_clip.py CLIP SECONDS [--player 1|2] [--frame N] [--pid PID | --process NAME] [--interval MS]
"""
import argparse, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mk4_live_log import find_pid

CLIP_BASE = 0x4FDD6C
STRUCT = {1: 0x522514, 2: 0x522598}     # +0 clip record>>2, +4 frame index, +8 frame data pointer>>2


class Mem:
    def __init__(self, pid):
        if sys.platform == 'win32':
            import ctypes as C
            self.C = C; self.k = C.WinDLL('kernel32', use_last_error=True)
            self.h = self.k.OpenProcess(0x0438, False, pid)     # VM_READ|VM_WRITE|VM_OPERATION|QUERY_INFORMATION
            if not self.h:
                raise SystemExit('OpenProcess failed')
        else:
            self.f = open('/proc/%d/mem' % pid, 'r+b', buffering=0)

    def read(self, a, n):
        if sys.platform == 'win32':
            C = self.C; b = C.create_string_buffer(n); r = C.c_size_t()
            self.k.ReadProcessMemory(self.h, C.c_void_p(a), b, n, C.byref(r)); return b.raw
        self.f.seek(a); return self.f.read(n)

    def write(self, a, data):
        if sys.platform == 'win32':
            C = self.C; r = C.c_size_t()
            self.k.WriteProcessMemory(self.h, C.c_void_p(a), data, len(data), C.byref(r)); return
        self.f.seek(a); self.f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('clip', type=int); ap.add_argument('seconds', type=float)
    ap.add_argument('--player', type=int, choices=(1, 2), default=1); ap.add_argument('--frame', type=int)
    ap.add_argument('--pid', type=int); ap.add_argument('--process', default='MK4.EXE')
    ap.add_argument('--interval', type=float, default=2.0, help='rewrite interval in ms')
    a = ap.parse_args()
    m = Mem(a.pid or find_pid(a.process)); base = STRUCT[a.player]
    rec = (CLIP_BASE + 12 * a.clip) >> 2
    data_ptr = None
    if a.frame is not None:                       # let the game switch to the clip, then derive its data start
        t1 = time.time()
        while time.time() - t1 < 0.1:
            m.write(base, struct.pack('<I', rec)); time.sleep(a.interval / 1000)
        fr, fp = struct.unpack('<II', m.read(base + 4, 8))
        data_ptr = (fp << 2) - 72 * fr            # fighter clips: 18 nodes x 4 bytes = 72 bytes per frame
    t0 = time.time()
    while time.time() - t0 < a.seconds:
        m.write(base, struct.pack('<I', rec))
        if data_ptr is not None:
            m.write(base + 4, struct.pack('<I', a.frame))
            m.write(base + 8, struct.pack('<I', ((data_ptr + 72 * a.frame) >> 2) & 0xFFFFFFFF))
        time.sleep(a.interval / 1000)
    print('done: player', a.player, 'clip', a.clip)


if __name__ == '__main__':
    main()
