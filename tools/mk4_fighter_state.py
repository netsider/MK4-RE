#!/usr/bin/env python3
"""MK4 PC (1998) fighter-object reader, READ-ONLY: prints or logs both fighters' state from a running game
(MK4_PC_FILE_FORMATS.txt section 9): clip, frame, X / height / Z, velocity, gravity, standing height, camera depth
and health. Never writes to the game.

Works on Windows (ReadProcessMemory) and on Linux under Wine (/proc/<pid>/mem); uses mk4_live_log.py from this
folder for process access. Python 3 standard library only.

Usage:
  python mk4_fighter_state.py [--pid PID | --process NAME]                  one snapshot of P1 and P2
  python mk4_fighter_state.py --log OUT.txt SECONDS [--interval MS] [...]   one line per change
  default --process MK4.EXE (use the exact name of your game executable); default --interval 2

Fields (all PROVEN for the 1,182,720-byte MK4.EXE; raw game units, 65536 = 1.0 unit, 16.16 fixed point):
  object  P1 = [0x5360D8] = 0x5224F0, P2 = [0x5360DC] = 0x522574 (P1 + 0x84)
  +0x24   clip record >> 2 -> clip = ((value << 2) - 0x4FDD6C) / 12     +0x28 frame index
  +0x48   standing (ground) height of the root     +0x4C gravity (added to vy each tick)
  +0x50   camera-space depth (view transform; NOT a world position)
  +0x54   X      +0x58 height (negative = up)      +0x5C Z depth
  +0x6C / +0x70 / +0x74   vx / vy / vz per tick
  health  P1 0x53865C, P2 0x535EAC (65536 = full bar), VS mode
Log line: t  then per player: clip frame x height z vx vy vz gravity health
"""
import argparse, os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mk4_live_log import Reader, find_pid   # noqa: E402

OBJ_PTR = (0x5360D8, 0x5360DC)
OBJ_DEFAULT = (0x5224F0, 0x522574)
HEALTH = (0x53865C, 0x535EAC)
CLIP_BASE = 0x4FDD6C
FIELDS = [('clip', 0x24), ('frame', 0x28), ('stand_h', 0x48), ('gravity', 0x4C), ('cam_depth', 0x50),
          ('x', 0x54), ('height', 0x58), ('z', 0x5C), ('vx', 0x6C), ('vy', 0x70), ('vz', 0x74)]
LOG_ORDER = ['clip', 'frame', 'x', 'height', 'z', 'vx', 'vy', 'vz', 'gravity', 'health']


def objects(rd):
    out = []
    for ptr, dflt in zip(OBJ_PTR, OBJ_DEFAULT):
        a = struct.unpack('<I', rd.read(ptr, 4))[0]
        out.append(a if 0x400000 <= a < 0x1000000 else dflt)
    return out


def state(rd, base, hp_addr):
    d = rd.read(base, 0x78); s = {}
    for name, off in FIELDS:
        v = struct.unpack_from('<i', d, off)[0]
        if name == 'clip':                       # -1 = no clip (record field 0, e.g. outside a fight)
            v = (((v & 0xFFFFFFFF) << 2) - CLIP_BASE) // 12 if v else -1
        s[name] = v
    s['health'] = struct.unpack('<i', rd.read(hp_addr, 4))[0]
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pid', type=int); ap.add_argument('--process', default='MK4.EXE')
    ap.add_argument('--log', nargs=2, metavar=('OUT', 'SECONDS'))
    ap.add_argument('--interval', type=float, default=2.0, help='poll interval in ms')
    a = ap.parse_args()
    rd = Reader(a.pid or find_pid(a.process))
    objs = objects(rd)
    if not a.log:
        for k, (base, hp) in enumerate(zip(objs, HEALTH)):
            s = state(rd, base, hp)
            print('P%d object 0x%06X' % (k + 1, base))
            for name, off in FIELDS:
                v = s[name]
                extra = '' if name in ('clip', 'frame') else '   (%+.4f units)' % (v / 65536)
                print('  +0x%02X %-9s %11d%s' % (off, name, v, extra))
            print('  health    %11d   (%.1f%% of the bar)' % (s['health'], 100 * s['health'] / 65536))
        return
    out, secs = a.log[0], float(a.log[1])
    last = None; t0 = time.time(); n = 0
    with open(out, 'w') as o:
        o.write('# t ' + ' '.join('P%d_%s' % (p, f) for p in (1, 2) for f in LOG_ORDER) + '\n')
        while time.time() - t0 < secs:
            row = []
            for base, hp in zip(objs, HEALTH):
                s = state(rd, base, hp); row += [s[f] for f in LOG_ORDER]
            if row != last:
                o.write('%.4f %s\n' % (time.time() - t0, ' '.join(map(str, row)))); last = row; n += 1
            time.sleep(a.interval / 1000)
    print('wrote', n, 'lines to', out)


if __name__ == '__main__':
    main()
