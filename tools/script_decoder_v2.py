#!/usr/bin/env python3
"""MK4 PC (1998) MK4.EXE script / command-list / strike decoder  -- self-contained.

Usage:  python3 script_decoder_v2.py MK4.EXE [command] [args]
  commands:
    lists                 decode all 18 fighters' command lists (input -> move word -> handler)
    fighter N             full per-fighter move table for fighter id N (0..17)
    table                 per-fighter table for all fighters (text)
    csv                   same as table, CSV
    script 0xADDR [fid]   linear decode of a script (fid -> follow op 3C/GOTO per fighter)
    strikes               dump strike (hitbox) tables + reaction ids
    reactions             dump reaction table 0x4ED4D0 -> victim clips/physics
    actions               dump the 5 action tables -> handler -> clips
Only needs Python 3 stdlib.  Reads the EXE read-only.

All addresses are for the retail MK4.EXE (1,182,720 bytes, image base 0x400000).
Tags: [P]=PROVEN [L]=LIKELY [G]=GUESS  (see MK4_PC_FILE_FORMATS.txt section 8B)
"""
import sys, struct, re, collections

# ---------------------------------------------------------------- PE loading
class Exe:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        d = self.d
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        nsec = struct.unpack_from('<H', d, pe + 6)[0]
        opt = struct.unpack_from('<H', d, pe + 20)[0]
        self.base = struct.unpack_from('<I', d, pe + 24 + 28)[0]
        self.secs = []
        so = pe + 24 + opt
        for i in range(nsec):
            name, vsz, va, rsz, rp = struct.unpack_from('<8sIIII', d, so + 40 * i)
            self.secs.append((name.rstrip(b'\0').decode(), self.base + va, vsz, rp, rsz))
        t = [s for s in self.secs if s[0] == '.text'][0]
        self.text = (t[1], t[1] + t[4])
    def off(self, va):
        for n, a, vsz, rp, rsz in self.secs:
            if a <= va < a + max(vsz, rsz):
                return rp + (va - a) if va - a < rsz else None
        return None
    def W(self, va):
        o = self.off(va)
        return 0 if o is None or o + 4 > len(self.d) else struct.unpack_from('<I', self.d, o)[0]
    def S(self, va):
        return struct.unpack('<i', struct.pack('<I', self.W(va)))[0]

# ---------------------------------------------------------------- constants
FIX_LISTS = (0x4D6E80, 0x4DC3F8)       # (dest,value) pairs, *dest |= value>>2   [P]
CLIP_TAB, CLIP_REC, NCLIP = 0x4FDD6C, 12, 700
OPTAB = 0x4E6970                        # script opcode handler table          [P]
REACT_TAB, NREACT = 0x4ED4D0, 194       # reaction (victim) handler table      [P]
ACTION_TABLES = [                       # selected by move-word byte2 bits     [P]
    ('misc', 0x4E9EE0, 0x48, 0x01), ('proj', 0x4F0810, 0x1B, 0x02),
    ('special', 0x4EB8F8, 0x23, 0x04), ('aux', 0x4E9FF0, 0x14, 0x08),
    ('bit5', 0x4E2C78, 0x2F, 0x20)]
CMD_BASE = 0x540448                     # 16 BSS tables x 18 fighters, 0x48 apart
P1_BUTTONS = [('UP', 0x540448), ('HP', 0x540490), ('LP', 0x5404D8), ('BL', 0x540520),
              ('HK', 0x540568), ('LK', 0x5405B0), ('Y?', 0x5405F8), ('RUN', 0x540688)]
CHECK_TAB = 0x4E7EA8                    # move-word byte3 -> condition fn
STRIKE_TABS = {0x51: 0x540E78, 0x50: 0x540E78, 0x52: 0x540E28, 0x53: 0x540D38, 0x5E: 0x540C80}
STRIKE_FN = {0x48D440: 0x540E78, 0x48D420: 0x540E28, 0x48D460: 0x540DC8,
             0x48D480: 0x540C80, 0x48D4A0: 0x540D38}
STRIKE_LEN = {0x540C80: 46, 0x540D38: 36, 0x540DC8: 24, 0x540E28: 20, 0x540E78: 41}  # BSS tables are contiguous
FID_ALIAS = {16: 2, 17: 7}              # op 3C remap                          [P]
SEQ = {0xdd: 'F', 0xaa: 'B', 0x02: 'D', 0x01: 'U'}   # dd/aa/02 [P], 01 [L]
# fighter id (obj+0x34) -> name. Sonya=2 PROVEN; others LIKELY from their command lists matching the
# known MK4 move inputs (e.g. 0: B,B+LP spear, D,B+HP teleport) and with the lower-case name pointer
# table at 0x4F11D8 (id order); 16/17 LIKELY from that table only (no own command list, op 3C remaps them).
FIGHTER = {0:'Scorpion',1:'Raiden',2:'Sonya',3:'Liu Kang',4:'Sub-Zero',5:'Fujin',6:'Shinnok',7:'Reiko',
           8:'Quan Chi',9:'Tanya',10:'Reptile',11:'Kai',12:'Jarek',13:'Jax',14:'Johnny Cage',15:'Goro',
           16:'Kitana',17:'Noob Saibot'}
FIGHTER_TAG = {i: ('PROVEN' if i == 2 else 'LIKELY') for i in range(18)}
# operand counts (words after the opcode word)
N = {0x01:1,0x02:1,0x09:1,0x17:1,0x71:1,0x08:2,0x54:1,0x0c:1,0x0e:1,0x0f:1,0x11:1,0x1a:1,0x1f:1,
     0x2f:1,0x32:1,0x33:1,0x35:1,0x36:2,0x38:1,0x3d:1,0x40:2,0x42:1,0x43:2,0x44:1,0x45:1,0x50:1,
     0x55:2,0x58:3,0x59:4,0x5a:1,0x5c:1,0x5d:2,0x5f:1,0x63:1,0x65:3,0x6c:2,0x6d:1,0x6f:1,0x70:1,
     0x3c:16}
FLAG2 = {0x46, 0x47, 0x48, 0x68, 0x49}  # one clip operand when (arg>>8)&0xff == 2
NAME = {0x0e:'OPP_CLIP',0x0f:'SET_CLIP',0x11:'START_CLIP',0x32:'NATIVE',0x33:'GOTO',0x3c:'FIGHTER_SWITCH',
        0x3e:'END',0x3f:'END_NATIVE',0x41:'CALL_REACTION',0x1e:'JMP_REACTION',0x70:'REACTION_IF_RANGE',
        0x47:'ANIM',0x48:'ANIM_TO_END',0x46:'ANIM46',0x68:'ANIM68',0x49:'ANIM49',0x4b:'ANIM_BOTH_UNTIL',
        0x51:'STRIKE',0x50:'STRIKE_W',0x52:'STRIKE_E28',0x53:'STRIKE_D38',0x5e:'STRIKE_C80',
        0x58:'VEL3(x,y,grav)',0x59:'VEL4',0x5f:'VELX',0x65:'VEL3B',0x5a:'PUSH',0x5c:'VELX_AIR',
        0x5d:'VEL2',0x63:'VEL1',0x22:'SET_GRAV_FN'}
END = {0x3e, 0x3f, 0x32, 0x1e}
PHYS = {0x58, 0x59, 0x5f, 0x65, 0x5a, 0x5c, 0x5d, 0x63}

class MK4:
    def __init__(self, path):
        self.x = x = Exe(path)
        self.FX = collections.defaultdict(list)
        for lst in FIX_LISTS:
            a = lst
            while True:
                dst, val = x.W(a), x.W(a + 4)
                if dst == 0 and val == 0: break
                self.FX[dst].append(val); a += 8
        self.CL = {}
        for dst, vs in self.FX.items():
            for v in vs:
                if CLIP_TAB <= v < CLIP_TAB + CLIP_REC * NCLIP and (v - CLIP_TAB) % CLIP_REC == 0:
                    self.CL[dst] = (v - CLIP_TAB) // CLIP_REC
        t0, t1 = x.text
        self.code = x.d[x.off(t0):x.off(t0) + (t1 - t0)]
        self.t0, self.t1 = t0, t1
        self.react = [x.W(REACT_TAB + 4 * i) for i in range(NREACT)]
        starts = set(h for h in self.react if t0 <= h < t1)
        for _, b, n, _ in ACTION_TABLES:
            starts |= set(x.W(b + 4 * i) for i in range(n) if t0 <= x.W(b + 4 * i) < t1)
        self.starts = sorted(starts)
        self.callers = collections.Counter()
        c = self.code
        for j in range(len(c) - 5):
            if c[j] == 0xE8:
                self.callers[(t0 + j + 5 + struct.unpack_from('<i', c, j + 1)[0]) & 0xffffffff] += 1
    # -- helpers
    def P(self, a):          # pointer stored at a (fixup or raw packed)
        return self.FX[a][0] if a in self.FX else None
    def extent(self, a, cap=0x1800):
        nx = [s for s in self.starts if s > a]
        return min(nx[0] if nx else a + 0x400, a + cap)
    def scan(self, a, e):
        """byte-scan code [a,e) for clip records, clip slots, script refs, strike blocks"""
        clips, slots, scripts, blocks = [], [], [], []
        x = self.x
        for o in range(a - self.t0, e - self.t0 - 3):
            v = struct.unpack_from('<I', self.code, o)[0]
            if CLIP_TAB <= v < CLIP_TAB + CLIP_REC * NCLIP and (v - CLIP_TAB) % CLIP_REC == 0:
                clips.append((v - CLIP_TAB) // CLIP_REC)
            elif v in self.CL and v >= 0x530000:
                slots.append(self.CL[v])
            elif 0x4D3000 <= v < 0x4F2000 and o > 0 and (self.code[o-1] == 0x68 or 0xB8 <= self.code[o-1] <= 0xBF):
                if x.W(v + 4) in STRIKE_FN: blocks.append((x.W(v + 4), x.W(v)))
                elif x.W(v + 8) in STRIKE_FN: blocks.append((x.W(v + 8), x.W(v + 4)))
                else: scripts.append(v)
        return clips, slots, scripts, blocks
    # -- strikes
    def strike(self, tab, i):
        if i >= STRIKE_LEN.get(tab, 64): return None
        r = self.P(tab + 4 * i)
        if r is None: return None
        x = self.x
        box = [x.S(r + 4 * k) / 65536 for k in range(4)]
        f = x.W(r + 0x10)
        return dict(rec=r, box=box, react=f & 0xff, react2=(f >> 8) & 0xff, b2=(f >> 16) & 0xff,
                    flags=f >> 24, w14=x.W(r + 0x14))
    def direct_strikes(self, a, e):
        """'mov [0x53FFEC],imm32' followed (<=24 bytes) by call/jmp to a strike fn  [P pattern]"""
        out = []
        lo, hi = a - self.t0, e - self.t0
        for mm in re.finditer(rb'\xc7\x05\xec\xff\x53\x00(....)', self.code[lo:hi], re.S):
            imm = struct.unpack('<I', mm.group(1))[0]
            p = lo + mm.end()
            for q in range(p, min(p + 24, len(self.code) - 5)):
                if self.code[q] in (0xE8, 0xE9):
                    t = (self.t0 + q + 5 + struct.unpack_from('<i', self.code, q + 1)[0]) & 0xffffffff
                    if t in STRIKE_FN:
                        st = self.strike(STRIKE_FN[t], imm & 0xff)
                        if st and imm < 0x100: out.append((hex(STRIKE_FN[t]), imm, st['react']))
                        break
        return out
    # -- reactions
    def reaction(self, n, _d=0):
        if n >= NREACT: return None
        h = self.react[n]
        if not (self.t0 <= h < self.t1): return None
        o = h - self.t0
        if self.code[o] == 0xE9 and _d < 3:          # leading jmp -> shared reaction code
            t = (h + 5 + struct.unpack_from('<i', self.code, o + 1)[0]) & 0xffffffff
            for k, hh in enumerate(self.react):
                if hh == t:
                    r = self.reaction(k, _d + 1); r = dict(r); r['handler'] = h; r['via'] = k; return r
        e = min(self.extent(h), h + 0x600)
        clips, slots, scripts, _ = self.scan(h, e)
        allc = clips + slots; phys = []
        for s in scripts:
            r = self.walk(s, 2, maxsteps=60, follow_native=False)
            allc += r['clips']; phys += r['phys']
        return dict(handler=h, clips=uniq(allc), phys=uniq(phys), via=None)
    # -- script decode
    def operand_count(self, w):
        op, arg = w >> 24, w & 0xffffff
        if op in FLAG2 and (arg >> 8) & 0xff == 2: return 1
        return N.get(op, 0)
    def fmt_operand(self, va):
        if va in self.CL: return 'CLIP%d' % self.CL[va]
        if va in self.FX: return '->0x%x' % self.FX[va][0]
        v = self.x.S(va)
        return str(v) if -0x10000 < v < 0x10000 else hex(v & 0xffffffff)
    def linear(self, a, n=80):
        out = []
        for _ in range(n):
            w = self.x.W(a); op, arg = w >> 24, w & 0xffffff
            k = self.operand_count(w)
            ops = [self.fmt_operand(a + 4 + 4 * j) for j in range(k)]
            if op == 0x3c: ops = ['f%d:%s' % (j, o) for j, o in enumerate(ops)]
            out.append('%x: %02x %-18s arg=%x %s' % (a, op, NAME.get(op, 'op%02x' % op), arg, ' '.join(ops)))
            a += 4 + 4 * k
            if op in (0x3e, 0x3f, 0x33, 0x1e): break
        return out
    def walk(self, s, fid, maxsteps=200, follow_native=True, depth=0, seen=None):
        """execute-follow a script for one fighter: GOTO + op3C per-fighter switch"""
        x = self.x; seen = seen if seen is not None else set()
        r = dict(clips=[], opp=[], phys=[], strikes=[], reacts=[], natives=[], path=[])
        pc = s; f = FID_ALIAS.get(fid, fid)
        for _ in range(maxsteps):
            if pc is None or pc in seen: break
            seen.add(pc); r['path'].append(pc)
            w = x.W(pc); op, arg = w >> 24, w & 0xffffff
            k = self.operand_count(w)
            if op == 0x3c:
                pc = self.P(pc + 4 + 4 * f); continue
            if op == 0x33:
                pc = self.P(pc + 4); continue
            for j in range(k):
                va = pc + 4 + 4 * j
                if va in self.CL:
                    (r['opp'] if op == 0x0e else r['clips']).append(self.CL[va])
            if op in PHYS:
                r['phys'].append('%02x %s' % (op, ','.join(str(x.S(pc + 4 + 4 * j)) for j in range(k)) or str(arg)))
            if op in STRIKE_TABS:
                st = self.strike(STRIKE_TABS[op], arg & 0xff)
                if st: r['strikes'].append((op, arg & 0xff, st['react'])); r['reacts'].append(st['react'])
            if op in (0x41, 0x1e, 0x70):
                r['reacts'].append(arg & 0xff)
            if op == 0x32:
                nat = x.W(pc + 4); r['natives'].append(nat)
                if follow_native and depth < 2 and self.t0 <= nat < self.t1:
                    for t3 in self.direct_strikes(nat, min(nat + 0x100, self.t1)):
                        r['strikes'].append(t3); r['reacts'].append(t3[2])
                    e = nat + 0x40
                    clips, slots, scripts, blocks = self.scan(nat, e)
                    r['clips'] += clips + slots
                    for fn, idx in blocks:
                        st = self.strike(STRIKE_FN[fn], idx & 0xff)
                        if st: r['strikes'].append(('blk', idx, st['react'])); r['reacts'].append(st['react'])
                    for sc in scripts:
                        q = self.walk(sc, fid, maxsteps, follow_native, depth + 1, seen)
                        for kk in r: r[kk] += q[kk]
            if op in (0x3e, 0x3f, 0x32, 0x1e): break
            pc += 4 + 4 * k
        return r
    # -- action handler for one fighter
    def action(self, tname, idx, fid):
        b = [t for t in ACTION_TABLES if t[0] == tname][0][1]
        h = self.x.W(b + 4 * idx)
        if not (self.t0 <= h < self.t1): return None
        e = self.extent(h)
        clips, slots, scripts, blocks = self.scan(h, e)
        r = dict(handler=h, clips=[], code_clips=clips + slots, opp=[], phys=[], strikes=[], reacts=[], natives=[], imm=[])
        for t3 in self.direct_strikes(h, e):
            r['strikes'].append(t3); r['reacts'].append(t3[2])
        # one level into private helpers called from the handler (<=16 callers, outside the extent)
        done = set()
        for j in range(h - self.t0, e - self.t0 - 5):
            if self.code[j] == 0xE8:
                t = (self.t0 + j + 5 + struct.unpack_from('<i', self.code, j + 1)[0]) & 0xffffffff
                if self.t0 <= t < self.t1 and not (h <= t < e) and t not in done and 0 < self.callers[t] <= 16 \
                        and abs(t - h) < 0x2000 and t not in STRIKE_FN:
                    done.add(t)
                    for t3 in self.direct_strikes(t, min(t + 0x180, self.t1)):
                        if t3 not in r['strikes']: r['strikes'].append(t3); r['reacts'].append(t3[2])
        for fn, i in blocks:
            st = self.strike(STRIKE_FN[fn], i & 0xff)
            if st: r['strikes'].append(('blk', i, st['react'])); r['reacts'].append(st['react'])
        seen = set()
        for sc in scripts:
            q = self.walk(sc, fid, seen=seen)
            for kk in ('clips', 'opp', 'phys', 'strikes', 'reacts', 'natives'): r[kk] += q[kk]
        r['clips'] += [c for c in r['code_clips'] if c not in r['clips']]
        # other "mov [0x53FFEC], imm" values in handler code: may be reaction ids (GUESS, noisy)
        lo, hi = h - self.t0, e - self.t0
        for mm in re.finditer(rb'\xc7\x05\xec\xff\x53\x00(.)\x00\x00\x00', self.code[lo:hi], re.S):
            r['imm'].append(mm.group(1)[0])
        return r
    # -- command lists
    def cmdlist(self, base, fid):
        p = self.P(base + 4 * fid)
        out = []
        if p is None: return p, out
        x = self.x
        while True:
            seq, ext, mw = x.W(p), x.W(p + 4), x.W(p + 8)
            if seq == 0: break
            out.append((p, seq, ext, mw)); p += 12
            if len(out) > 40: break
        return self.P(base + 4 * fid), out

def uniq(l):
    o = []
    for v in l:
        if v not in o: o.append(v)
    return o

def seq_str(seq):
    if seq == 0xffffffff: return '(button only)'
    bs = []
    while seq:
        bs.append(SEQ.get(seq & 0xff, '%02x' % (seq & 0xff))); seq >>= 8
    return ','.join(bs)

def mw_split(mw):
    b3, b2, b1, b0 = mw >> 24, (mw >> 16) & 0xff, (mw >> 8) & 0xff, mw & 0xff
    tabs = [t[0] for t in ACTION_TABLES if b2 & t[3]]
    return dict(cond=b3, flags=b2, window=b1, idx=b0, table=tabs[0] if tabs else 'misc')

def describe(m, tname, idx, fid):
    r = m.action(tname, idx, fid)
    if not r: return None
    vic = []
    for rid in uniq(r['reacts']):
        rv = m.reaction(rid)
        vic.append((rid, rv['clips'] if rv else [], rv['phys'] if rv else []))
    return r, vic


# ---------------------------------------------------------------- per-fighter table
# basic moves: (label, input, table, idx). Input<->handler link is PROVEN for Sonya by clip match
# against SONYA_PROVEN_TABLE.txt and LIKELY for the other fighters (same handler, per-fighter op 3C).
BASIC = [('Low punch', 'LP', 'misc', 0x08), ('High punch', 'HP', 'misc', 0x0B),
         ('High kick', 'HK', 'misc', 0x05), ('Low kick', 'LK', 'misc', 0x04),
         ('Uppercut', 'D+HP', 'misc', 0x01), ('Sweep', 'B+LK', 'misc', 0x06),
         ('Roundhouse', 'B+HK', 'misc', 0x07), ('Jump punch HP', 'U then HP', 'misc', 0x0A),
         ('Jump punch LP', 'U then LP', 'misc', 0x0E), ('Jump angled HK', 'U+F/B then HK', 'misc', 0x10),
         ('Jump angled LK', 'U+F/B then LK', 'misc', 0x11), ('Jump-up kick', 'U then HK/LK', 'misc', 0x0D),
         ('Crouch LP', 'D+LP', 'aux', 0x0E), ('Crouch kicks', 'D+HK / D+LK', 'aux', 0x0D),
         ('Throw', 'LP/F+LP close', 'misc', 0x02), ('Close strike (knee/elbow?)', 'HK close? (GUESS)', 'misc', 0x09),
         ('Crouch block', 'D+BL', 'aux', 0x0F), ('Run', 'F,F+RUN hold', 'bit5', 0x03)]
# Sonya PROVEN (attacker clips, victim first clips) keyed by (table, idx)
SONYA_PROVEN = {('misc', 8): ([294], [311]), ('misc', 0xB): ([296], [311, 324]), ('misc', 5): ([65], [311]),
    ('misc', 4): ([308], [134]), ('misc', 1): ([293], [128]), ('misc', 6): ([63], [195]),
    ('misc', 7): ([313], []), ('misc', 0xA): ([97], []), ('misc', 0xE): ([96], [186]),
    ('misc', 0x10): ([57], [131]), ('misc', 0x11): ([60], [186]), ('misc', 0xD): ([327], []),
    ('aux', 0xE): ([260], []), ('aux', 0xD): ([53, 315], []), ('misc', 2): ([78], [156]),
    ('aux', 0xF): ([257], []), ('bit5', 3): ([317, 307], []),
    ('special', 5): ([310, 101], [305]), ('special', 6): ([72, 73], [136]), ('special', 7): ([102], [201]),
    ('special', 0x13): ([104], [131]), ('proj', 5): ([15], [130]), ('misc', 0x29): ([244], [])}
MW_NAME = {('misc', 0x29): 'weapon draw',
           ('misc', 0x40): 'fatality A (misc40) LIKELY', ('misc', 0x43): 'fatality B (misc43) LIKELY',
           ('misc', 0x41): 'finisher slot misc41 (cond 1A) GUESS', ('misc', 0x42): 'finisher slot misc42 (cond 33; uppercut 293->128, stage fatality?) GUESS',
           ('misc', 0x03): 'generic RUN-button action (clip 209)', ('misc', 0x0f): 'generic RUN-button action 2'}

def row_for(m, fid, tname, idx):
    r = m.action(tname, idx, fid)
    if not r: return None
    vic, vphys, rids = [], [], []
    for rid in uniq(r['reacts']):
        rv = m.reaction(rid)
        rids.append(rid)
        if rv: vic.append((rid, rv['clips'])); vphys += ['r%02x:%s' % (rid, p) for p in rv['phys']]
    return dict(handler=r['handler'], clips=uniq(r['clips']), opp=uniq(r['opp']), strikes=uniq(r['strikes']),
                rids=rids, vic=vic, vphys=uniq(vphys), aphys=uniq(r['phys']), imm=uniq(r['imm']))

def check_sonya(fid, key, row):
    if fid != 2 or key not in SONYA_PROVEN or row is None: return ''
    pa, pv = SONYA_PROVEN[key]
    a_ok = all(c in row['clips'] for c in pa)
    allv = row['opp'] + [c for _, cl in row['vic'] for c in cl]
    v_ok = (not pv) or any(c in allv for c in pv)
    return 'SONYA-CHECK attacker %s / victim %s' % ('MATCH' if a_ok else 'MISS', ('MATCH' if v_ok else 'not-resolved') if pv else 'n/a')

def fighter_rows(m, fid):
    rows = []
    for label, inp, t, i in BASIC:
        rows.append(('basic', label, inp, None, t, i))
    for bn, base in P1_BUTTONS:
        _, recs = m.cmdlist(base, fid)
        for addr, seq, ext, mw in recs:
            s = mw_split(mw)
            inp = (seq_str(seq) + '+' + bn) if seq != 0xffffffff else bn + ' (button combo/charge)'
            rows.append(('command', MW_NAME.get((s['table'], s['idx']), '%s[%02x]' % (s['table'], s['idx'])), inp, mw, s['table'], s['idx']))
    out = []
    for cat, label, inp, mw, t, i in rows:
        r = row_for(m, fid, t, i)
        out.append((cat, label, inp, mw, t, i, r, check_sonya(fid, (t, i), r)))
    return out

def tagrow(fid, cat, r, chk):
    if 'attacker MATCH' in chk: return 'PROVEN' if 'victim MATCH' in chk or 'victim n/a' in chk else 'PROVEN(att)/victim-unresolved'
    if r is None: return 'GUESS'
    if not r['clips']: return 'GUESS'
    return 'LIKELY' if FIGHTER_TAG[fid] != 'GUESS' else 'GUESS'

def fmt_vic(r):
    v = []
    if r['opp']: v.append('opp-clip ' + '-'.join(map(str, r['opp'])))
    for rid, cl in r['vic']: v.append('r%02x->%s' % (rid, '-'.join(map(str, cl)) or '?'))
    return '; '.join(v) or '-'

def print_table(m, fids, csvmode=False):
    import csv
    if csvmode:
        w = csv.writer(sys.stdout)
        w.writerow(['fid', 'fighter', 'fighter_tag', 'category', 'move', 'input', 'move_word', 'table', 'idx', 'handler',
                    'attacker_clips', 'strikes(table,idx,reaction)', 'reaction_ids', 'victim_clips', 'victim_physics',
                    'attacker_physics', 'tag', 'sonya_check'])
    for fid in fids:
        if not csvmode:
            print('=' * 100); print('FIGHTER %d  %s  [name %s]' % (fid, FIGHTER[fid], FIGHTER_TAG[fid])); print('=' * 100)
        for cat, label, inp, mw, t, i, r, chk in fighter_rows(m, fid):
            tag = tagrow(fid, cat, r, chk)
            if r is None:
                if not csvmode: print('  %-7s %-28s %-24s %s[%02x] no handler' % (cat, label, inp, t, i))
                continue
            if csvmode:
                w.writerow([fid, FIGHTER[fid], FIGHTER_TAG[fid], cat, label, inp, '%08x' % mw if mw else '', t, '%02x' % i,
                            '0x%x' % r['handler'], ' '.join(map(str, r['clips'])),
                            ' '.join('%s/%x/r%02x' % (a if isinstance(a, str) else 'op%02x' % a, b, c) for a, b, c in r['strikes']),
                            ' '.join('%02x' % x for x in r['rids']), fmt_vic(r), ' | '.join(r['vphys'][:4]),
                            ' | '.join(r['aphys'][:4]), tag, chk])
            else:
                print('  %-7s %-30s input=%-26s %s %s[%02x] h=0x%x  [%s]' % (cat, label, inp, ('mw=%08x' % mw) if mw else '',
                      t, i, r['handler'], tag))
                print('          attacker: %s' % (' '.join(map(str, r['clips'])) or '- (not resolved statically)'))
                print('          victim  : %s' % fmt_vic(r))
                if r['aphys']: print('          att.phys: %s' % ' | '.join(r['aphys'][:5]))
                if r['vphys']: print('          vic.phys: %s' % ' | '.join(r['vphys'][:5]))
                if chk: print('          %s' % chk)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    m = MK4(sys.argv[1]); cmd = sys.argv[2] if len(sys.argv) > 2 else 'lists'
    a = sys.argv[3:]
    if cmd == 'script':
        s = int(a[0], 16)
        if len(a) > 1:
            r = m.walk(s, int(a[1]))
            for k, v in r.items(): print(k, [hex(t) if k in ('path', 'natives') else t for t in v])
        else:
            print('\n'.join(m.linear(s, 200)))
    elif cmd == 'strikes':
        for op, tab in sorted(set((v, k) for k, v in STRIKE_FN.items())):
            print('== strike table 0x%x (fn 0x%x)' % (op, tab))
            for i in range(64):
                st = m.strike(op, i)
                if st: print('  %02x rec=0x%x box=%s react=0x%02x react2=0x%02x b2=%d flags=%x w14=%d' % (
                    i, st['rec'], ['%.3f' % b for b in st['box']], st['react'], st['react2'], st['b2'], st['flags'], st['w14']))
    elif cmd == 'reactions':
        for i in range(NREACT):
            r = m.reaction(i)
            if r: print('0x%02x h=0x%x clips=%s phys=%s' % (i, r['handler'], r['clips'], r['phys']))
    elif cmd == 'actions':
        for t, b, n, _ in ACTION_TABLES:
            for i in range(n):
                r = m.action(t, i, 2)
                if r: print('%-7s %02x h=0x%x clips(f2)=%s reacts=%s' % (t, i, r['handler'], uniq(r['clips']), uniq(r['reacts'])))
    elif cmd in ('table', 'csv'):
        print_table(m, range(18), cmd == 'csv')
    elif cmd == 'fighter':
        print_table(m, [int(a[0])])
    elif cmd == 'lists':
        for fid in range(18):
            print('== fighter %d %s' % (fid, FIGHTER.get(fid, '')))
            for bn, base in P1_BUTTONS:
                p, recs = m.cmdlist(base, fid)
                for addr, seq, ext, mw in recs:
                    s = mw_split(mw)
                    print('  %-4s %-14s mw=%08x cond=%02x win=%d %s[%02x]' % (bn, seq_str(seq), mw, s['cond'], s['window'], s['table'], s['idx']))
    else:
        print(__doc__)

if __name__ == '__main__':
    main()
