MK4 PC (1998) reverse-engineering tools
=======================================
Author: netsider. Companion to ..\MK4_PC_FILE_FORMATS.txt (the format guide) and ..\MK4_RE_NOTES_v3.txt (the notes).
No game data is included: every tool reads YOUR OWN copy of MK4.EXE / FILESYS.DAT (or a running game) at a path
given on the command line. All addresses are for the retail MK4.EXE of 1,182,720 bytes; other builds will differ.
Python 3.8+. Run any tool with no arguments (or -h) to print its usage.

Static file tools (any OS)
--------------------------
fsys_tool.py          FILESYS.DAT lister/extractor. Recovers all 799 entry names by hashing candidate paths built from
                      MK4.EXE strings (guide sections 1-2).  Deps: stdlib.
                        python fsys_tool.py FILESYS.DAT MK4.EXE list
                        python fsys_tool.py FILESYS.DAT MK4.EXE extract OUTDIR
                        python fsys_tool.py FILESYS.DAT - hash "C:\SOURCE\MK4\WIN\GEOGFX\SZ_GEO.GEO"
export_pc_geo.py      .GEO mesh exporter: GEO parts + texture -> GLB, plus texture PNG and a front/side preview
                      (guide section 3). Fighters: the type-1 parts. Files with no type-1 parts (logos midway_g /
                      MKlogo_g / attract_ = type 0x4, buyin_ge, arenas): every 3D part. 2D sprite records are
                      skipped. UV byte 0 = texture page; if a mesh uses several pages they are stacked into one
                      atlas PNG.  Deps: Pillow.
                        python export_pc_geo.py FILESYS.DAT OUTDIR SB_GEO.GEO      (or ALL = every fighter, per-part GLB)
                        python export_pc_geo.py FILESYS.DAT OUTDIR MIDWAY_G.GEO MKLOGO_G.GEO ATTRACT_.GEO
extract_textures.py   Every RLE-555 texture page of every GEO -> PNG, one contact sheet per GEO, and MENU.TGA
                      (guide section 3).  Deps: Pillow; uses fsys_tool.py and export_pc_geo.py from this folder.
                        python extract_textures.py FILESYS.DAT MK4.EXE OUTDIR
esf2wav.py            ESF sounds -> WAV (8-bit PCM or 4-bit IMA ADPCM; 11025/22050 Hz) (guide section 4).  Deps: stdlib.
                        python esf2wav.py FILESYS.DAT OUTDIR
                        python esf2wav.py --file SOUND.ESF OUT.WAV
ecm_tool.py           ECM video decoder (M_*.ECM): EDL decompressor, 320x240 frames -> PNG, IMA ADPCM sound -> WAV
                      (guide section 5). Output matches MK4.EXE's own routines except the game's random softening
                      of solid-colour blocks.  Deps: Pillow (frames only); info and wav use the stdlib.
                        python ecm_tool.py M_MIDWAY.ECM info
                        python ecm_tool.py M_MIDWAY.ECM frames OUTDIR [first last step]
                        python ecm_tool.py M_MIDWAY.ECM wav OUT.wav
anim_emu.py           Animation frame decoder that runs MK4.EXE's own decompressor (VA 0x4013A0) in an emulator, so
                      output matches the game exactly (guide sections 5-6).  Deps: numpy, unicorn.
                        python anim_emu.py DIR info               (DIR holds MK4.EXE, ANIMDAT4.AP0, ANIMDAT4.AP1;
                        python anim_emu.py DIR dump 293 out.csv    get AP0/AP1 with fsys_tool.py extract)
script_decoder_v2.py  MK4.EXE script / command-list / strike / reaction decoder: input -> move word -> handler -> clips,
                      per-fighter move tables (guide sections 8, 8A, 8B).  Deps: stdlib.  Reads the EXE read-only.
                        python script_decoder_v2.py MK4.EXE lists | fighter N | table | csv | strikes | reactions
                        python script_decoder_v2.py MK4.EXE actions | script 0xADDR [fid]
script_decoder_v3.py  v2 plus: opcode reference (all 128 script opcodes, operand counts, effect, PROVEN/LIKELY/GUESS),
                      condition table 0x4E7EA8 meanings, sound tables -> pcmkNNNN.esf names, per-move sounds and damage,
                      button/player table map, annotated script listing (guide sections 8A, 8B).  Deps: stdlib.
                        python script_decoder_v3.py MK4.EXE ops | conds | sounds | buttons
                        python script_decoder_v3.py MK4.EXE movesounds [fid] | dis 0xADDR [fid]
                        (all v2 commands still work; optional --sounds LIST adds your own per-file notes)

Live-game tools (your own running copy)
---------------------------------------
mk4_live_log.py       READ-ONLY logger: P1/P2 clip id, frame and position words, one line per change (guide section 9).
                      Windows (ReadProcessMemory) or Linux/Wine (/proc/<pid>/mem).  Deps: stdlib.
                        python mk4_live_log.py log.txt 30 --process MK4.EXE
mk4_force_clip.py     WRITES game memory: forces a player to play a clip, optionally frozen on one frame
                      (guide section 9). For capture/inspection.  Windows or Linux/Wine.  Deps: stdlib.
                        python mk4_force_clip.py 293 5 --player 1 [--frame 10] --process MK4.EXE
mk4_input.py          Windows: sends key presses with SendInput scan codes (DirectInput sees them); scripted inputs
                      such as "RIGHT+J:60 wait:200". Never touches game memory.  Deps: stdlib.
                        python mk4_input.py --focus "ENTER:80 wait:500 RIGHT+J:60"
mk4_config.py         Windows: decodes the game's registry 'Config' blob (XOR (i*0x7B)&0xFF, checksum); read-only
                      unless --reset-joystick (sets the P1 joystick int to 0 and fixes the checksum).  Deps: stdlib.
                        python mk4_config.py            python mk4_config.py --file blob.bin

Process names: pass the name of your game executable with --process (or use --pid).
Live addresses (0x5225xx etc.) are static .bss addresses of the same 1,182,720-byte build.
