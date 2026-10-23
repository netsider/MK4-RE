#!/usr/bin/env python3
"""MK4 PC (1998) MK4.EXE script / command-list / strike decoder  -- self-contained.

Usage:  python3 script_decoder_v3.py MK4.EXE [command] [args]
  commands:
    lists                 decode all 18 fighters' command lists (input -> move word -> handler)
    fighter N             full per-fighter move table for fighter id N (0..17)
    table                 per-fighter table for all fighters (text)
    csv                   same as table, CSV
    script 0xADDR [fid]   linear decode of a script (fid -> follow op 3C/GOTO per fighter)
    strikes               dump strike (hitbox) tables + reaction ids
    reactions             dump reaction table 0x4ED4D0 -> victim clips/physics
    actions               dump the 5 action tables -> handler -> clips
  new in v3:
    ops                   opcode reference (0x00-0x7F): name, operand words, effect, tag
    conds                 move-word condition table 0x4E7EA8 (b3) with meaning
    sounds                sound tables used by script ops 20/25/26/27/2B/2C/73/74/75 -> code -> pcmkNNNN
    buttons               the 16 command tables: button, player, input bit, matcher
    dis 0xADDR [fid]      linear decode with annotations (sound -> pcmk, strike damage %, velocities)
    movesounds [fid]      per move: sounds played and damage (strikes + op 63), for one or all fighters 0..15
  option (any command):
    --sounds SOUNDS_INDEX.txt   a text list with lines 'pcmkNNNN.wav ... [tag] text' (e.g. made with esf2wav.py
                                plus your own notes); pcmk names then show that text and missing files are flagged
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
    ('misc', 0x4E9EE0, 0x44, 0x01), ('proj', 0x4F0810, 0x1B, 0x02),
    ('special', 0x4EB8F8, 0x23, 0x04), ('aux', 0x4E9FF0, 0x14, 0x08),
    ('bit5', 0x4E2C78, 0x50, 0x20)]   # v3: sizes from table layout (section 8A of the guide)
CMD_BASE = 0x540448                     # 16 BSS tables x 18 fighters, 0x48 apart
P1_BUTTONS = [('UP', 0x540448), ('HP', 0x540490), ('LP', 0x5404D8), ('BL', 0x540520),
              ('HK', 0x540568), ('LK', 0x5405B0), ('LKrel', 0x5405F8), ('RUN', 0x540688)]
P2_BUTTONS = [('UP', 0x5406D0), ('HP', 0x540718), ('LP', 0x540760), ('BL', 0x5407A8),
              ('HK', 0x5407F0), ('LK', 0x540838), ('LKrel', 0x540640), ('RUN', 0x540880)]
CHECK_TAB = 0x4E7EA8                    # move-word byte3 -> condition fn
STRIKE_TABS = {0x51: 0x540E78, 0x50: 0x540E78, 0x52: 0x540E28, 0x53: 0x540D38, 0x5E: 0x540C80}
STRIKE_FN = {0x48D440: 0x540E78, 0x48D420: 0x540E28, 0x48D460: 0x540DC8,
             0x48D480: 0x540C80, 0x48D4A0: 0x540D38}
STRIKE_LEN = {0x540C80: 46, 0x540D38: 36, 0x540DC8: 24, 0x540E28: 20, 0x540E78: 41}  # BSS tables are contiguous
FID_ALIAS = {16: 2, 17: 7}              # op 3C remap                          [P]
SEQ = {0xdd: 'F', 0xaa: 'B', 0x02: 'D', 0x01: 'U'}   # dd/aa/02 [P], 01 [L: joystick bit 0x01 = event code 1]
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
     0x55:2,0x58:3,0x59:4,0x5a:1,0x5c:1,0x5d:2,0x5f:1,0x63:1,0x65:3,0x6c:1,0x6d:1,0x6f:1,0x70:1,
     0x3c:16, 0x1b:1}   # v3: 6C = 1 word (+ arg split 12/12), 1B = 1 word  [P: fetch-helper count]
FLAG2 = {0x46, 0x47, 0x48, 0x68, 0x49}  # one clip operand when (arg>>8)&0xff == 2
NAME = {0x0e:'OPP_CLIP',0x0f:'SET_CLIP',0x11:'START_CLIP',0x32:'NATIVE',0x33:'GOTO',0x3c:'FIGHTER_SWITCH',
        0x3e:'END',0x3f:'END_NATIVE',0x41:'CALL_REACTION',0x1e:'JMP_REACTION',0x70:'REACTION_IF_RANGE',
        0x47:'ANIM',0x48:'ANIM_TO_END',0x46:'ANIM46',0x68:'ANIM68',0x49:'ANIM49',0x4b:'ANIM_BOTH_UNTIL',
        0x51:'STRIKE',0x50:'STRIKE_W',0x52:'STRIKE_E28',0x53:'STRIKE_D38',0x5e:'STRIKE_C80',
        0x58:'VEL3(x,y,grav)',0x59:'VEL4',0x5f:'VELX',0x65:'VEL3B',0x5a:'PUSH',0x5c:'VELX_AIR',
        0x5d:'VEL2',0x63:'VEL1',0x22:'SET_GRAV_FN'}
END = {0x3e, 0x3f, 0x32, 0x1e}
PHYS = {0x58, 0x59, 0x5f, 0x65, 0x5a, 0x5c, 0x5d, 0x63}


# ---------------------------------------------------------------- v3: opcode reference (D1)
# (name, effect, tag). Operand words come from N / FLAG2 above. "byte" = low 8 bits of the opcode word.
# Tags from disassembly of each handler in OPTAB; [P] control flow read directly, [L] meaning inferred.
OPS = {
 0x00:('NOP','no-op (also the dispatcher entry)','P'), 0x0b:('NOP','no-op','P'), 0x15:('NOP','no-op','P'),
 0x18:('NOP','no-op','P'), 0x21:('NOP','no-op','P'), 0x23:('NOP','no-op','P'), 0x57:('NOP','no-op','P'),
 0x66:('NOP','no-op','P'), 0x67:('NOP','no-op','P'),
 0x01:('ANIM_CLIP','w=clip: animate from the current frame (0x428D10)','L'),
 0x02:('ANIM_N','w=clip, then the 0x429490 tick loop','L'),
 0x03:('ANIM_CUR','animate the current clip (+0x24) to its end, yields each tick (0x429780)','L'),
 0x04:('ANIM_TICKS','byte=n: animate n ticks, stop early at clip end (0x429490)','P'),
 0x05:('WAIT_ANIM','byte=n: [0x540000]=n, then per-tick routine 0x428D70 (wait n ticks while animating)','L'),
 0x06:('ANIM_TICKS2','byte=n: animate n ticks, other variant (0x4293C0)','P'),
 0x07:('ANIM_COUNT','loop while anim+0x28 > 0, decrementing it (0x429380)','P'),
 0x08:('ANIM08','2 words (0x4284E0)','L'), 0x09:('CLIP09','w=clip (0x429460)','L'),
 0x0a:('FRAME_ADD','anim+0x28 += byte','P'), 0x0c:('SET2','anim+0x28=byte, w -> secondary obj, then 0D','P'),
 0x0d:('OP0D','0x4285B0','L'), 0x0e:('OPP_CLIP','opponent clip=w, frame 0','P'),
 0x0f:('SET_CLIP','anim+0x28=byte, clip=w','P'), 0x10:('WAIT_BOTH','wait byte ticks animating both fighters','P'),
 0x11:('START_CLIP','w=clip: start clip (0x406B20), +0x28=byte','P'), 0x12:('FRAME_SET','anim+0x28=byte','P'),
 0x13:('FRAME_LAST','anim+0x28=last frame','P'), 0x14:('OP14','0x429970 with last frame','L'),
 0x16:('FLAG_535E84','[0x535E84]=1','P'), 0x17:('CLIP17','w=clip (0x4283A0)','L'),
 0x19:('REPEAT','repeat byte times','L'), 0x1a:('CLIP_WAIT','w=clip, frame 0, wait 200 ticks','L'),
 0x1b:('SET_540000','[0x540000]=byte, 1 word','P'), 0x1c:('ANIM_FRAMES','animate byte frames','L'),
 0x1d:('OP1D','0x429970 frame=byte','L'), 0x1e:('JMP_REACTION','jump to reaction byte (ends script)','P'),
 0x1f:('SET_68','obj+0x68=w (move class)','P'),
 0x20:('SND_TAB20','sound: table 0x4ED998[byte]; byte > 0x32 plays nothing','P'), 0x22:('SET_GRAV_FN','obj+0x4C = 0x457D00','P'),
 0x24:('EFFECT24','0x470F20 (condition on 0x48F340)','L'),
 0x25:('SND_TAB25','sound: table 0x4EDD18[byte]','P'), 0x26:('SND_TAB26','sound: table 0x4EDAE0[byte]','P'),
 0x27:('SND_TAB27','sound: table 0x4EDA00[byte]','P'),
 0x28:('OP28','0x457D00 (gravity/landing helper)','L'),
 0x29:('STATE_1006','obj+0x74=0x1006','P'), 0x2a:('SPAWN_FX','[0x53FFFC]=byte, spawn process 0x457BE0 (effect)','L'),
 0x2b:('SND_VOICE','sound: per-fighter voice list 0x540BC0[byte] (random pick)','P'),
 0x2c:('SND_FIGHTER','sound: 0x540C60[byte] -> u16[fighter]','P'),
 0x2d:('STATE_1007','obj+0x74=0x1007','P'), 0x2e:('OP2E','0x490190, mode 8 -> 0x490280','L'),
 0x2f:('IF_HEIGHT','w=target: height/airborne test, goto w or fall through','P'),
 0x30:('RET_NATIVE','return to calling native (0x41F780)','P'),
 0x32:('NATIVE','w=native function: jump to native code (ends script)','P'), 0x33:('GOTO','w=target','P'),
 0x34:('SLEEP','sleep byte ticks','P'), 0x35:('CALL_NATIVE','w=native function: call and continue','P'),
 0x36:('CALL_IF','w1=native, w2=target: call, goto w2 if bit 4','P'),
 0x37:('SLEEP12','sleep (arg split 12/12)','P'), 0x38:('SET_ANIM44','anim+0x44 = w (per-tick callback)','P'),
 0x39:('CLR_ANIM44','anim+0x44 = 0','P'), 0x3a:('LOOP_START','obj+0x78 = byte (loop count)','P'),
 0x3b:('LOOP_END','decrement obj+0x78, jump back after the previous 3A','P'),
 0x3c:('FIGHTER_SWITCH','16 words: per-fighter target (16->2, 17->7)','P'),
 0x3d:('IF_540008','w=target: goto if [0x540008]==1 (blocked)','L'),
 0x3e:('END','end of script (return to stance)','P'), 0x3f:('END_NATIVE','landing / end native','P'),
 0x40:('OP40','2 words (0x49CB50: spawn process)','L'), 0x41:('CALL_REACTION','call reaction byte','P'),
 0x42:('IF_BIT0','w=target: goto if condition bit0 set','P'),
 0x43:('CALL_IF_BIT0','w1=native, w2=target: call, then goto if bit0','P'),
 0x44:('IF_44','w=target: 0x48EB90 condition goto','L'), 0x45:('IF_AIRBORNE','w=target: 0x48EEB0 airborne goto','P'),
 0x46:('ANIM46','animate (0x429040), optional clip word when byte1==2','P'),
 0x47:('ANIM','animate (0x428D30), optional clip word when byte1==2','P'),
 0x48:('ANIM_TO_END','animate to end (0x428D50), optional clip word','P'),
 0x49:('ANIM49','0x429970, optional clip word','P'),
 0x4a:('ANIM_UNTIL','byte=n: animate until anim+0x28 <= n (0x4292F0, yields each tick)','P'),
 0x4b:('ANIM_BOTH_UNTIL','animate both fighters (0x45BE30)','P'), 0x4c:('ANIM_BOTH2','animate both fighters (0x45BF00)','P'),
 0x4d:('OP4D','0x429230','L'), 0x4e:('SET_53FD04','[0x53FD04] = anim obj','P'), 0x4f:('OP4F','0x431520(byte)','L'),
 0x50:('STRIKE_W','byte=index, w=target: strike 0x540E78, goto w on hit','P'),
 0x51:('STRIKE','strike 0x540E78[byte]','P'), 0x52:('STRIKE_E28','strike 0x540E28[byte]','P'),
 0x53:('STRIKE_D38','strike 0x540D38[byte] (index 8 stops sound 0x1392 on a miss)','P'),
 0x54:('SLEEP12B','sleep (arg split 12/12)','P'), 0x55:('CALL_BYTE_IF','w1=native(byte), w2=target','P'),
 0x56:('OP56','0x4315B0(byte)','L'),
 0x58:('VEL3','x,y,grav: forward velocity, Y velocity, gravity (16.16)','P'),
 0x59:('VEL4','4 words (0x490960)','L'), 0x5a:('VEL_BACK','v: velocity -v along facing (push back)','P'),
 0x5b:('STOP','stop all motion','P'), 0x5c:('GRAVITY','g: gravity','P'),
 0x5d:('NUDGE','dist,dy: position nudge','P'), 0x5e:('STRIKE_C80','strike 0x540C80[byte]','P'),
 0x5f:('VELX','v: forward velocity','P'), 0x60:('OP60','0x48F3E0','L'), 0x61:('CLR_FLAG0','anim+0x40 &= ~1','P'),
 0x62:('OP62','table 0x4D3818 call (gated)','L'), 0x63:('DAMAGE','w = damage (16.16 of the health bar) to the opponent','P'),
 0x64:('OP64','0x490C20','L'), 0x65:('VEL_OPP','v,vy,grav: velocity relative to the opponent','P'),
 0x68:('ANIM68','animate (0x428E80), optional clip word','P'), 0x69:('OP69','0x428EA0','L'), 0x6a:('OP6A','0x429200','L'),
 0x6b:('AS_OPP','run a callback as the opponent (0x48FD50)','L'),
 0x6c:('ORBIT','stop; obj+0x5C/+0x64 = arg 12/12 bits, obj+0x60 = w, anim+0x44 = 0x4948B0','P'),
 0x6d:('OP6D','w (0x42CEB0)','L'), 0x6e:('AS_OPP2','run 0x494570 as the opponent','L'),
 0x6f:('IF_6F','w=target: 0x48F150 compare','L'), 0x70:('REACTION_IF_RANGE','reaction if in range','P'),
 0x71:('OP71','w -> secondary object; large handler','L'), 0x72:('OP72','0x42B8C0','L'),
 0x73:('SND_RAND','sound: random code 0x64A or 0x66D','P'), 0x74:('SND_627','sound: code 0x627','P'),
 0x75:('SND_TANYA','sound 0x4EDD18[0x1A] if own fighter id == 9','P'), 0x76:('INPUT76','large handler (input matcher 0x45C6B0)','L'),
 0x7c:('INPUT7C','large handler','L'),
}
for _o in range(0x80):
    OPS.setdefault(_o, ('op%02x' % _o, 'default handler 0x49CBB0' if _o in (0x78,0x79,0x7a,0x7b,0x7d,0x7e,0x7f) else 'not analysed', 'G'))
for _o, (_n, _d, _t) in OPS.items():
    NAME.setdefault(_o, _n)
SOUND_OPS = {0x20, 0x25, 0x26, 0x27, 0x2b, 0x2c, 0x73, 0x74, 0x75}

# ---------------------------------------------------------------- v3: conditions (D4)
# move word b3 -> 0x4E7EA8[b3]. A condition vetoes the move by clearing bit0 of [0x54000C].
# T(n) = ticks since this player's event timestamp n (0x48E440: [0x538418] - [0x53FE68 + (2n+player)*4]).
# held(...) = buttons that must be held: (input & mask) == want on the two active-low input words
#   0x4D30A4 (bits 0x10 HP, 0x20 BL, 0x40 HK, 0x01 Up) and 0x4D30A8 (bits 1 LP, 2 LK, 4 RUN).
# dist = [0x533D5C] (distance between the fighters, 16.16; name LIKELY).
# arena = [0x53849C] (indexes per-arena tables, e.g. the music codes at 0x4DDD18; LIKELY arena number).
CONDS = {
 0x00:'none',
 0x01:'T(2) >= 64', 0x02:'own state +0x74 == 0x2001', 0x03:'own +0x30 == 0 and own anim flag bit1 clear',
 0x04:'3D distance test (0x45EF40)', 0x05:'T(0) >= 64', 0x06:'3D distance test (0x45EF40)',
 0x07:'opponent hit count (+0x7C) < 3', 0x08:'T(6) >= 180',
 0x09:'opponent state not 0x100D/0x1001/0x1002', 0x0a:'opponent state == 0x1001',
 0x0b:'opponent hit count compare (0x45F600)', 0x0c:'held-button test (list 0x4E7208, GUESS)',
 0x0d:'held BL + LK, Up not held', 0x0e:'own Y (+0x58) <= -1.8 (0xFFFE3334)',
 0x0f:'opponent state != 0x100A', 0x10:'held BL + LP',
 0x11:'opponent state != 0x100B, then timer [0x528A04]/[0x538418] >= 120',
 0x12:'gravity test (anim +0x4C)', 0x13:'T(3) >= 48',
 0x14:'opponent state not 0x1001/0x100D, then timer >= 90', 0x15:'T(0x13) >= 90', 0x16:'T(4) >= 32',
 0x17:'held BL + HK only, Up not held', 0x18:'T(7) >= 80', 0x19:'T(9) >= 48',
 0x1a:'arena == 8 (stage finisher)', 0x1b:'dist <= 1.0 (close)',
 0x1c:'held HP + BL + RUN, Up not held (+[0x540440] path)', 0x1d:'T(0xA) >= 80', 0x1e:'T(0xB) >= 70',
 0x1f:'T(0xC) >= 60', 0x20:'[0x528A08]/[0x53FD34]/[0x53FD7C] count <= 4', 0x21:'T(0xD) >= 60',
 0x22:'T(0xF) >= 80', 0x23:'T(0x10) >= 90', 0x24:'dist >= 1.3', 0x25:'dist >= 1.8 (far)',
 0x26:'held BL + HK + LK, Up not held', 0x27:'held BL + RUN (0x45F460 variant) and [0x538678] == 0xE',
 0x28:'(null entry: always passes)', 0x29:'held BL + HK + LP + LK, Up not held', 0x2a:'timer >= 240',
 0x2b:'held HP + BL, Up not held', 0x2c:'held HP + HK + LP + LK', 0x2d:'held BL + HK only',
 0x2e:'timer >= 240', 0x2f:'dist >= 1.0', 0x30:'(null entry)', 0x31:'T(0x12) >= 80',
 0x32:'round not won yet ([0x535F14] == 0)', 0x33:'arena == 0 (stage finisher)', 0x34:'(null entry)',
}

# ---------------------------------------------------------------- v3: sounds (D2)
SND_TABLES = {0x20: (0x4ED998, 51), 0x25: (0x4EDD18, 66), 0x26: (0x4EDAE0, 20), 0x27: (0x4EDA00, 113)}
MUSIC_TAB = 0x4F5CC8      # u32 codes; a match goes to the music/CD path 0x4AC5E0 instead of a pcmk file  [P]
VOICE_COL = 0x4EDD00      # s8 column per fighter id for op 2B                                          [P]

SOUND_TEXT = {}       # optional: pcmkNNNN -> recogniser text, filled by --sounds SOUNDS_INDEX.txt

def load_sound_index(path):
    """read a SOUNDS_INDEX.txt-style file: lines 'pcmkNNNN.wav ... [ASR-xxx] text'"""
    for ln in open(path, encoding='utf-8', errors='replace'):
        if ln.startswith('pcmk'):
            k = ln[:8]
            t = ln.split(']', 1)[1].strip() if '] ' in ln else ''
            SOUND_TEXT[k] = t[:30]

def pcmk(code, music=()):
    """sound code -> file name, as sound_call 0x4BD7C0 does it  [P]"""
    if code in (0, 0xffff, -1): return 'stop-all'
    if code == 0xfffe: return 'stop(-2)'
    if code < 100 and code in music: return 'music(%d)' % code
    n = 2000 + code if code <= 100 else code // 5
    k = 'pcmk%04d' % n
    if SOUND_TEXT:
        if k not in SOUND_TEXT: return k + '(no such file)'
        if SOUND_TEXT[k]: return '%s"%s"' % (k, SOUND_TEXT[k])
    return k

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
    def linear(self, a, n=80, fid=2):
        out = []
        for _ in range(n):
            w = self.x.W(a); op, arg = w >> 24, w & 0xffffff
            k = self.operand_count(w)
            ops = [self.fmt_operand(a + 4 + 4 * j) for j in range(k)]
            if op == 0x3c: ops = ['f%d:%s' % (j, o) for j, o in enumerate(ops)]
            note = self.annotate(a, fid)
            out.append('%x: %02x %-18s arg=%x %s%s' % (a, op, NAME.get(op, 'op%02x' % op), arg, ' '.join(ops), ('   ; ' + note) if note else ''))
            a += 4 + 4 * k
            if op in (0x3e, 0x3f, 0x33, 0x1e): break
        return out
    def walk(self, s, fid, maxsteps=200, follow_native=True, depth=0, seen=None):
        """execute-follow a script for one fighter: GOTO + op3C per-fighter switch"""
        x = self.x; seen = seen if seen is not None else set()
        r = dict(clips=[], opp=[], phys=[], strikes=[], reacts=[], natives=[], path=[], sounds=[], damage=[])
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
            if op in SOUND_OPS:
                r['sounds'] += self.sound_codes(op, arg, fid)
            if op == 0x63:
                r['damage'].append(('op63', x.S(pc + 4)))
            if op in STRIKE_TABS:
                st = self.strike(STRIKE_TABS[op], arg & 0xff)
                if st: r['damage'].append(('%02x[%x]' % (op, arg & 0xff), st['w14']))
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
        r = dict(handler=h, clips=[], code_clips=clips + slots, opp=[], phys=[], strikes=[], reacts=[], natives=[], imm=[], sounds=[], damage=[])
        for t3 in self.direct_strikes(h, e):
            r['strikes'].append(t3); r['reacts'].append(t3[2])
            st = self.strike(int(t3[0], 16), t3[1])
            if st: r['damage'].append(('nat%s[%x]' % (t3[0][-3:], t3[1]), st['w14']))
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
            for kk in ('clips', 'opp', 'phys', 'strikes', 'reacts', 'natives', 'sounds', 'damage'): r[kk] += q[kk]
        r['clips'] += [c for c in r['code_clips'] if c not in r['clips']]
        # other "mov [0x53FFEC], imm" values in handler code: may be reaction ids (GUESS, noisy)
        lo, hi = h - self.t0, e - self.t0
        for mm in re.finditer(rb'\xc7\x05\xec\xff\x53\x00(.)\x00\x00\x00', self.code[lo:hi], re.S):
            r['imm'].append(mm.group(1)[0])
        return r

    # -- v3: sounds (D2)
    def u16(self, va):
        o = self.x.off(va)
        return 0 if o is None else struct.unpack_from('<H', self.x.d, o)[0]
    def music_codes(self):
        return set(self.x.W(MUSIC_TAB + 4 * i) for i in range(14)) - {0}
    def sound_codes(self, op, arg, fid=2):
        """codes a sound opcode can play for fighter fid -> list of u16 codes (several = random pick)"""
        b = arg & 0xff; x = self.x; f = FID_ALIAS.get(fid, fid)
        if op in SND_TABLES:
            t, n = SND_TABLES[op]
            c = self.u16(t + 2 * b) if b < n else 0
            return [c] if c else []
        if op == 0x75: return [self.u16(SND_TABLES[0x25][0] + 2 * 0x1a)]   # only when own fighter id == 9
        if op == 0x73: return [0x64a, 0x66d]
        if op == 0x74: return [0x627]
        if op == 0x2c:
            X = self.P(0x540C60 + 4 * b)
            if X is None: return []
            c = self.u16(X + 2 * f); return [c] if c else []
        if op == 0x2b:
            X = self.P(0x540BC0 + 4 * b)
            if X is None: return []
            fid2 = 0xa if fid == 0x10 else fid
            col = struct.unpack('<b', bytes([x.d[x.off(VOICE_COL + fid2)]]))[0]
            if x.W(X) != 0:
                c = self.u16(X + 2 * col); return [c] if c else []
            L = self.P(X + 4 * (col + 1))
            if L is None: return []
            n = self.u16(L)
            return [self.u16(L + 2 + 2 * k) for k in range(min(n, 16)) if self.u16(L + 2 + 2 * k)]
        return []
    def snd_str(self, op, arg, fid=2):
        mu = self.music_codes()
        cs = self.sound_codes(op, arg, fid)
        return '/'.join('%s(0x%x)' % (pcmk(c, mu), c) for c in cs) or '-'
    def annotate(self, pc, fid=2):
        """v3: human note for one script word (sound, damage, strike, condition)"""
        x = self.x; w = x.W(pc); op, arg = w >> 24, w & 0xffffff
        if op in SOUND_OPS: return 'sound ' + self.snd_str(op, arg, fid)
        if op == 0x63: return 'damage %.1f%%' % (x.S(pc + 4) * 100 / 65536)
        if op in STRIKE_TABS:
            st = self.strike(STRIKE_TABS[op], arg & 0xff)
            if st: return 'strike: hit r%02x / air r%02x / blocked r%02x, flags %x, damage %.1f%% (blocked %.1f%%)' % (
                st['react'], st['react2'], st['b2'], st['flags'], st['w14'] * 100 / 65536, st['w14'] * 20 / 65536)
        if op in (0x58, 0x65):
            return 'vel/grav ' + ', '.join('%.4f' % (x.S(pc + 4 + 4 * j) / 65536) for j in range(3))
        if op in (0x5a, 0x5c, 0x5f): return '%.4f' % (x.S(pc + 4) / 65536)
        if op == 0x5d: return 'nudge %.4f, %.4f' % (x.S(pc + 4) / 65536, x.S(pc + 8) / 65536)
        return ''
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
           ('misc', 0x40): 'fatality A (misc40, finisher clip id+1) LIKELY', ('misc', 0x43): 'fatality B (misc43, finisher clip id+0x10) LIKELY',
           ('misc', 0x41): 'stage fatality, arena 8 (misc41, clip 0x1F) LIKELY', ('misc', 0x42): 'stage fatality, arena 0 (misc42, uppercut 293) LIKELY',
           ('misc', 0x13): 'morph Scorpion', ('misc', 0x14): 'morph Raiden', ('misc', 0x15): 'morph Sonya',
           ('misc', 0x16): 'morph Liu Kang', ('misc', 0x17): 'morph Sub-Zero', ('misc', 0x18): 'morph Fujin',
           ('misc', 0x19): 'morph Jarek', ('misc', 0x1a): 'morph Quan Chi', ('misc', 0x1b): 'morph Tanya',
           ('misc', 0x1c): 'morph Reptile', ('misc', 0x1d): 'morph Kai', ('misc', 0x1e): 'morph Jax',
           ('misc', 0x24): 'morph Reiko', ('misc', 0x25): 'morph Johnny Cage',
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
    if '--sounds' in sys.argv:                       # optional sound list with recogniser text
        i = sys.argv.index('--sounds'); load_sound_index(sys.argv[i + 1]); del sys.argv[i:i + 2]
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
    elif cmd == 'dis':
        fid = int(a[1]) if len(a) > 1 else 2
        print('\n'.join(m.linear(int(a[0], 16), 200, fid)))
    elif cmd == 'ops':
        for o in range(0x80):
            nm, de, tg = OPS[o]
            h = m.x.W(OPTAB + 4 * o)
            nw = N.get(o, 0)
            print('%02X  h=0x%06x  %-16s words=%s  %s  [%s]' % (o, h, nm, ('%d' % nw) + ('(+1 if byte1==2)' if o in FLAG2 else ''), de, tg))
    elif cmd == 'conds':
        for i in range(0x39):
            fn = m.x.W(CHECK_TAB + 4 * i)
            print('%02X  fn=0x%06x  %s' % (i, fn, CONDS.get(i, 'not analysed' if fn else '(null)')))
    elif cmd == 'sounds':
        mu = m.music_codes()
        print('music codes (0x4F5CC8):', sorted(mu))
        for op, (t, n) in sorted(SND_TABLES.items()):
            print('== op %02X table 0x%X (%d entries, index = low byte of the opcode word)' % (op, t, n))
            for i in range(n):
                c = m.u16(t + 2 * i)
                if c: print('  %02x  code 0x%04x  %s' % (i, c, pcmk(c, mu)))
        print('== op 2C table 0x540C60[byte] -> u16[fighter id 0..15]')
        for b in range(2):                          # only 2C 00 is used by scripts; 01 also looks valid
            X = m.P(0x540C60 + 4 * b)
            if X: print('  %02x  ' % b + ' '.join('%s' % pcmk(m.u16(X + 2 * f), mu) for f in range(16)))
        print('== op 2B table 0x540BC0[byte] -> voice column 0x4EDD00[fighter] -> code or random list')
        for b in range(0x0d):                       # 0x540BC0 holds 13 pointers; scripts use 03/07/08/0A
            if m.P(0x540BC0 + 4 * b) is None: continue
            cols = []
            for f in (0, 1, 2, 3, 4, 9, 15):        # one fighter per voice column 0..6
                cols.append('f%d:%s' % (f, m.snd_str(0x2b, b, f)))
            print('  %02x  ' % b + '  '.join(cols))
        print('== op 73: pcmk%04d or pcmk%04d (random)   op 74: pcmk%04d   op 75: 0x4EDD18[0x1A] for fighter 9 only'
              % (0x64a // 5, 0x66d // 5, 0x627 // 5))
    elif cmd == 'buttons':
        print('input word 0x4D30A4 (active low): joystick 0x01-0x08 (0x01 = Up LIKELY), HP 0x10, BL 0x20, HK 0x40; P2 = bits << 8')
        print('input word 0x4D30A8 (active low): LP 0x01, LK 0x02, RUN 0x04; P2 = bits << 4')
        print('press dispatch lists 0x4E7250 (word A) / 0x4E72C8 (word B); release list 0x4E7300 (word B)')
        for (n1, b1), (n2, b2) in zip(P1_BUTTONS, P2_BUTTONS):
            print('  %-6s P1 0x%06X (matcher 0x45DCC0)   P2 0x%06X (matcher 0x45DD20)' % (n1, b1, b2))
    elif cmd == 'movesounds':
        fids = [int(a[0])] if a else range(16)
        mu = m.music_codes()
        for fid in fids:
            print('== fighter %d %s' % (fid, FIGHTER[fid]))
            seen = set()
            rows = [(lab, inp, t, i) for lab, inp, t, i in BASIC]
            for bn, base in P1_BUTTONS:
                for addr, seq, ext, mw in m.cmdlist(base, fid)[1]:
                    sp = mw_split(mw)
                    inp = (seq_str(seq) + '+' + bn) if seq != 0xffffffff else bn
                    rows.append((MW_NAME.get((sp['table'], sp['idx']), '%s[%02x]' % (sp['table'], sp['idx'])) + ' cond%02x' % sp['cond'], inp, sp['table'], sp['idx']))
            for lab, inp, t, i in rows:
                r = m.action(t, i, fid)
                if not r: continue
                snd = uniq(r['sounds']); dmg = uniq(r['damage'])
                print('  %-34s %-18s %s[%02x]  sounds: %s   damage: %s' % (lab[:34], inp[:18], t, i,
                      ' '.join(pcmk(c, mu) for c in snd) or '-',
                      ' '.join('%s=%.1f%%' % (k, v * 100 / 65536) for k, v in dmg) or '-'))
    elif cmd == 'strikes':
        for op, tab in sorted(set((v, k) for k, v in STRIKE_FN.items())):
            print('== strike table 0x%x (fn 0x%x)' % (op, tab))
            for i in range(64):
                st = m.strike(op, i)
                if st: print('  %02x rec=0x%x box=%s hit=r%02x air=r%02x blocked=r%02x flags=%x damage=%d (%.1f%% of the bar)' % (
                    i, st['rec'], ['%.3f' % b for b in st['box']], st['react'], st['react2'], st['b2'], st['flags'], st['w14'], st['w14'] * 100 / 65536))
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
