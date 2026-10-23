#!/usr/bin/env python3
"""MK4 PC (1998) input driver for Windows: sends keys with SendInput hardware scan codes (KEYEVENTF_SCANCODE),
which the game's DirectInput keyboard reads. Sends keys only; never touches game memory. Python 3 stdlib only.

Usage:
  python mk4_input.py [--focus] [--title "Mortal Kombat 4"] "SEQ"
  SEQ tokens: KEY:ms (hold KEY for ms), KEY+KEY:ms (chord), wait:ms
  KEY names: W Z A S U J T G SPACE B M H ENTER ESC 1 2 UP DOWN LEFT RIGHT (map them to your in-game key setup)
Example:  python mk4_input.py --focus "ENTER:80 wait:500 RIGHT+J:60"
"""
import ctypes as C, ctypes.wintypes as W, sys, time

SC = {'W': 0x11, 'Z': 0x2C, 'A': 0x1E, 'S': 0x1F, 'U': 0x16, 'J': 0x24, 'T': 0x14, 'G': 0x22, 'SPACE': 0x39,
      'B': 0x30, 'M': 0x32, 'H': 0x23, 'ENTER': 0x1C, 'ESC': 0x01, '1': 0x02, '2': 0x03,
      'UP': 0x48, 'DOWN': 0x50, 'LEFT': 0x4B, 'RIGHT': 0x4D}
EXT = {'UP', 'DOWN', 'LEFT', 'RIGHT'}


class KI(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class IU(C.Union):
    _fields_ = [('ki', KI), ('pad', C.c_byte * 32)]


class INP(C.Structure):
    _fields_ = [('type', W.DWORD), ('u', IU)]


u = C.WinDLL('user32', use_last_error=True)


def key(n, up):
    f = 0x8 | (0x2 if up else 0) | (0x1 if n in EXT else 0)
    i = INP(1, IU(ki=KI(0, SC[n], f, 0, 0))); u.SendInput(1, C.byref(i), C.sizeof(INP))


def focus(title):
    h = u.FindWindowW(None, title)
    if not h:
        sys.exit('no window titled %r' % title)
    u.keybd_event(0x12, 0, 0, 0); u.SetForegroundWindow(h); u.keybd_event(0x12, 0, 2, 0); time.sleep(0.5)


def run(seq):
    for tok in seq.split():
        k, ms = tok.split(':'); ms = int(ms)
        if k.lower() == 'wait':
            time.sleep(ms / 1000); continue
        ks = k.upper().split('+')
        for x in ks: key(x, False)
        time.sleep(ms / 1000)
        for x in reversed(ks): key(x, True)
        time.sleep(0.05)


if __name__ == '__main__':
    a = sys.argv[1:]; title = 'Mortal Kombat 4'; do_focus = False
    while a and a[0].startswith('--'):
        if a[0] == '--focus': do_focus = True; a = a[1:]
        elif a[0] == '--title': title = a[1]; a = a[2:]
        else: sys.exit(__doc__)
    if not a: sys.exit(__doc__)
    if do_focus: focus(title)
    run(a[0])
