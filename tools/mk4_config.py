#!/usr/bin/env python3
"""MK4 PC (1998) registry 'Config' blob decoder (Windows). Read-only unless --reset-joystick is given.

The game keeps its settings in a REG_BINARY value 'Config' (0x24C bytes) under
  HKLM\\SOFTWARE\\[WOW6432Node\\]GT Interactive\\Mortal Kombat 4\\1.00
(on modern Windows often redirected to HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\...).
Format: every byte i is XORed with (i * 0x7B) & 0xFF. After un-XOR, u32 at +0 is a checksum
= 0x43464729 + sum(signed_byte[i] << (i % 23)) for i = 4..0x247 (mod 2^32) (PROVEN: matched on the copy studied);
s32 at +0x240/+0x244 are the P1/P2 joystick selections (LIKELY).

Usage:
  python mk4_config.py [--key REGPATH] [--hklm]                 print checksum status, joystick ints, hex dump
  python mk4_config.py ... --reset-joystick                    set the P1 joystick int to 0, fix checksum, write back
  python mk4_config.py --file BLOB.bin                          decode a saved raw blob instead of the registry
"""
import argparse, struct, sys

HKLM_KEY = r'SOFTWARE\WOW6432Node\GT Interactive\Mortal Kombat 4\1.00'
DEFAULT_KEY = r'Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\GT Interactive\Mortal Kombat 4\1.00'


def xor(b):
    return bytearray(x ^ ((i * 0x7B) & 0xFF) for i, x in enumerate(b))


def checksum(d):
    s = 0x43464729
    for i in range(4, 0x248):
        v = d[i] - 256 if d[i] > 127 else d[i]
        s = (s + (v << (i % 23))) & 0xFFFFFFFF
    return s


def show(d):
    print('length 0x%X  checksum ok: %s  P1/P2 joystick: %s' % (
        len(d), checksum(d) == struct.unpack_from('<I', d, 0)[0], struct.unpack_from('<ii', d, 0x240)))
    for o in range(0, len(d), 16):
        print('%04X  %s' % (o, d[o:o + 16].hex(' ')))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--key', help='registry path (default: the VirtualStore path for HKCU, the WOW6432Node path for HKLM)')
    ap.add_argument('--hklm', action='store_true', help='read HKEY_LOCAL_MACHINE instead of HKEY_CURRENT_USER')
    ap.add_argument('--file'); ap.add_argument('--reset-joystick', action='store_true')
    a = ap.parse_args()
    if a.file:
        d = xor(open(a.file, 'rb').read())
        if len(d) < 0x248:
            sys.exit('blob too short')
        show(d); return
    import winreg
    root = winreg.HKEY_LOCAL_MACHINE if a.hklm else winreg.HKEY_CURRENT_USER
    access = winreg.KEY_READ | (winreg.KEY_SET_VALUE if a.reset_joystick else 0)
    h = winreg.OpenKey(root, a.key or (HKLM_KEY if a.hklm else DEFAULT_KEY), 0, access)
    raw, _ = winreg.QueryValueEx(h, 'Config')
    if len(raw) != 0x24C:
        sys.exit('unexpected Config length 0x%X' % len(raw))
    d = xor(raw); show(d)
    if a.reset_joystick:
        struct.pack_into('<i', d, 0x240, 0); struct.pack_into('<I', d, 0, checksum(d))
        winreg.SetValueEx(h, 'Config', 0, winreg.REG_BINARY, bytes(xor(d)))
        d2 = xor(winreg.QueryValueEx(h, 'Config')[0])
        print('written; checksum ok: %s  P1/P2 joystick: %s' % (
            checksum(d2) == struct.unpack_from('<I', d2, 0)[0], struct.unpack_from('<ii', d2, 0x240)))


if __name__ == '__main__':
    main()
