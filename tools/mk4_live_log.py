#!/usr/bin/env python3
"""MK4 PC (1998) live logger, READ-ONLY: logs P1/P2 clip id, frame and the three position words while the game runs
(MK4_PC_FILE_FORMATS.txt section 9). Never writes to the game.

Works on Windows (OpenProcess + ReadProcessMemory) and on Linux under Wine (/proc/<pid>/mem; needs ptrace
permission, e.g. same user and kernel.yama.ptrace_scope=0, or run as root). Python 3 standard library only.

Usage:
  python mk4_live_log.py OUT.txt SECONDS [--pid PID | --process NAME] [--interval MS]
  default --process MK4.EXE (use the exact name of your game executable); default --interval 2
Output: one line per change: t  P1clip P1frame P1a P1b P1c  P2clip P2frame P2a P2b P2c
  clip = ((record_field << 2) - 0x4FDD6C) / 12; a/b/c = record +0x2C/+0x30/+0x34 (P1: 0x522540 vertical,
  0x522544 X, 0x522548 depth/height).  Addresses are for the 1,182,720-byte MK4.EXE.
"""
import argparse, struct, subprocess, sys, time

P1, P2 = 0x522514, 0x522598
CLIP_BASE = 0x4FDD6C


def find_pid(name):
    if sys.platform == 'win32':
        outp = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq %s' % name, '/FO', 'CSV', '/NH'], text=True)
        for line in outp.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[0].lower() == name.lower():
                return int(parts[1])
    else:
        outp = subprocess.run(['pgrep', '-x', name[:15]], capture_output=True, text=True).stdout.split()
        if outp:
            return int(outp[0])
    raise SystemExit('process %s not found (use --pid)' % name)


class Reader:
    def __init__(self, pid):
        if sys.platform == 'win32':
            import ctypes as C
            self.C = C; self.k = C.WinDLL('kernel32', use_last_error=True)
            self.h = self.k.OpenProcess(0x0410, False, pid)          # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
            if not self.h:
                raise SystemExit('OpenProcess failed')
        else:
            self.f = open('/proc/%d/mem' % pid, 'rb', buffering=0)

    def read(self, addr, n):
        if sys.platform == 'win32':
            C = self.C; b = C.create_string_buffer(n); r = C.c_size_t()
            if not self.k.ReadProcessMemory(self.h, C.c_void_p(addr), b, n, C.byref(r)):
                raise OSError('ReadProcessMemory failed at 0x%X' % addr)
            return b.raw
        self.f.seek(addr); return self.f.read(n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out'); ap.add_argument('seconds', type=float)
    ap.add_argument('--pid', type=int); ap.add_argument('--process', default='MK4.EXE')
    ap.add_argument('--interval', type=float, default=2.0, help='poll interval in ms')
    a = ap.parse_args()
    rd = Reader(a.pid or find_pid(a.process))
    last = None; t0 = time.time(); n = 0
    with open(a.out, 'w') as o:
        while time.time() - t0 < a.seconds:
            row = []
            for base in (P1, P2):
                d = rd.read(base, 0x40)
                rec, fr = struct.unpack_from('<II', d, 0); y, x, z = struct.unpack_from('<iii', d, 0x2C)
                row += [((rec << 2) - CLIP_BASE) // 12, fr, y, x, z]
            if row != last:
                o.write('%.4f %s\n' % (time.time() - t0, ' '.join(map(str, row)))); last = row; n += 1
            time.sleep(a.interval / 1000)
    print('wrote', n, 'lines to', a.out)


if __name__ == '__main__':
    main()
