"""Export PC MK4 GEO meshes (fighters, arenas, ...) from FILESYS.DAT to GLB plus a preview PNG.

Usage:
  python export_pc_geo.py FILESYS.DAT OUTDIR [NAME.GEO ...]   e.g. SZ_GEO.GEO (default), or ALL for every
                                                               fighter in ROSTER as one-node-per-part GLBs
Needs: Python 3, Pillow.  Also importable: fsys_hash(), parse_blocks(), triangles_of(), decode_rle555().

The mesh layout is the one mk4decomp's geo_mesh.py checked against the
game: 16-byte blocks, field-relative offsets, 12-byte int16 verts,
triangle strips, then 8-byte UV rows. Type 1 is the first set of parts.
Type 0 repeats the same counts, so it stays out of the file.
Files without type-1 parts (logos: type 0x4; arenas/effects: 0, 0x2, 0x40, 0x100) export
all their 3D parts instead. Records with byte 0 bit 7 set (0x80/0x81) are 2D sprite
records, not meshes; they are skipped. UV row byte 0 is the GEO-local texture page
(MK4.EXE VA 0x4BB943); when a mesh uses more than one page the pages are stacked into
one atlas PNG and the UVs are remapped.

Positions are the game's int16, divided by 100, Y up. One PNG from the
GEO is embedded. metallicFactor is 0 so Lumen does not darken it.
"""
import json
import os
import struct
import sys

from PIL import Image, ImageDraw

PATH = "FILESYS.DAT"   # set from the command line
OUT = "out"            # set from the command line
PREFIX = "C:\\SOURCE\\MK4\\WIN\\GEOGFX\\"

# Disc filename -> output label. Two-letter codes not confirmed by a render keep their code as the label.
ROSTER = {
    "SC_GEO.GEO": "scorpion",
    "SZ_GEO.GEO": "subzero",
    "LK_GEO.GEO": "liukang",
    "JC_GEO.GEO": "johnnycage",
    "JX_GEO.GEO": "jax",
    "JA_GEO.GEO": "jarek",
    "TA_GEO.GEO": "tanya",
    "RA_GEO.GEO": "raiden",
    "SB_GEO.GEO": "sonya",
    "RE_GEO.GEO": "re_geo",
    "QC_GEO.GEO": "qc_geo",
    "KI_GEO.GEO": "ki_geo",
    "ME_GEO.GEO": "me_geo",
    "NS_GEO.GEO": "ns_geo",
    "SH_GEO.GEO": "sh_geo",
    "GO_GEO.GEO": "go_geo",
    "WG_GEO.GEO": "wg_geo",
}


def fsys_hash(path):
    upper = path.upper()
    h, shift = 0, 0
    for ch in upper:
        b = ord(ch)
        if b >= 0x80:
            b -= 0x100
        h = (h + (b << shift)) & 0xFFFFFFFF
        shift = (shift + 8) if shift < 24 else 0
    return (h + len(upper)) & 0xFFFFFFFF


def parse_blocks(data):
    tex_off, size = struct.unpack_from("<II", data, 4)
    blocks = []
    o = 0x0C
    while o + 16 <= tex_off and len(blocks) < 4096:
        typ, cnt, a, b, c = struct.unpack_from("<HHiii", data, o)
        if typ & 0x80:
            o += 16          # 2D sprite record (draw code VA 0x4BB180), not a mesh
            continue
        if cnt == 0:
            break
        vtx_off = o + 4 + a
        strip_off = o + 8 + b
        if not (0 < strip_off < tex_off and 0 < vtx_off < tex_off):
            break
        strips = []
        s = strip_off
        total = 0
        nvert = 0
        while s + 4 <= len(data):
            flag, n = struct.unpack_from("<Hh", data, s)
            s += 4
            if n < 0:
                break
            strips.append((flag, n))
            total += n + 1
            nvert += n + 3
            if len(strips) > 256:
                break
        if total != cnt or vtx_off + 12 * nvert != o + 12 + c:
            break
        blocks.append({
            "type": typ, "count": cnt, "nvert": nvert,
            "vtx_off": vtx_off, "strips": strips,
            "tri_off": o + 12 + c,
        })
        o += 16
    return tex_off, blocks


def decode_rle555(data, tex_off):
    """First texture in the GEO, RGB from the 5-5-5 word the decomp confirmed."""
    p = tex_off + 4
    (count,) = struct.unpack_from("<I", data, p)
    p += 4
    textures = []
    for _ in range(count):
        w, h, sz = struct.unpack_from("<HHI", data, p)
        p += 8
        src = p
        end = p + sz
        img = Image.new("RGB", (w, h))
        pix = img.load()
        for row in range(h):
            x = 0
            while x < w and src + 1 < end:
                token = data[src] | (data[src + 1] << 8)
                src += 2
                if (token & 0x8000) == 0:
                    color = token
                    run = 1
                else:
                    low = token & 0x7FFF
                    color = low
                    run = data[src] if src < end else 0
                    src += 1
                r = ((color >> 10) & 31) * 255 // 31
                g = ((color >> 5) & 31) * 255 // 31
                b = (color & 31) * 255 // 31
                for k in range(run):
                    if x >= w:
                        break
                    pix[x, row] = (r, g, b)
                    x += 1
        textures.append(img)
        p = end
    return textures


def triangles_of(data, block):
    """Yield (xyz, uv) for each corner. xyz is int16. uv is 0..1."""
    verts = []
    for k in range(block["nvert"]):
        x, y, z, nx, ny, nz = struct.unpack_from("<6h", data, block["vtx_off"] + k * 12)
        verts.append((x, y, z))
    cursor = 0
    ti = 0
    out = []
    for flag, n in block["strips"]:
        for i in range(n + 1):
            # Strip order is vert i, i+1, i+2. The next row repeats the
            # last two UV pairs, so the bytes belong to those verts.
            # Swapping the corners for winding must not take the UV with it.
            ia, ib, ic = cursor + i, cursor + i + 1, cursor + i + 2
            raw = data[block["tri_off"] + ti * 8: block["tri_off"] + ti * 8 + 8]
            ti += 1
            uv_of = {
                ia: (raw[2] / 255.0, 1.0 - raw[3] / 255.0),
                ib: (raw[4] / 255.0, 1.0 - raw[5] / 255.0),
                ic: (raw[6] / 255.0, 1.0 - raw[7] / 255.0),
            }
            order = [ia, ib, ic]
            if i & 1:
                order[1], order[2] = order[2], order[1]
            if flag & 1:
                order[1], order[2] = order[2], order[1]
            tri = [(verts[vi], uv_of[vi], raw[0]) for vi in order]   # raw[0] = texture page
            out.append(tri)
        cursor += n + 3
    return out


def pad4(blob):
    return blob + b"\x00" * ((4 - len(blob) % 4) % 4)


def write_glb(path, tris, png_bytes, label):
    # Unweld so each corner keeps its own UV.
    pos = b""
    nor = b""
    uv = b""
    idx = b""
    xs, ys, zs = [], [], []
    n = 0
    for tri in tris:
        pts = [c[0] for c in tri]
        ax, ay, az = pts[0]
        bx, by, bz = pts[1]
        cx, cy, cz = pts[2]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        nx, ny, nz = nx / length, ny / length, nz / length
        for (x, y, z), (u, v), _slot in tri:
            # /100 puts a fighter a bit over 2 units tall. Y is already up.
            px, py, pz = x / 100.0, y / 100.0, z / 100.0
            pos += struct.pack("<3f", px, py, pz)
            nor += struct.pack("<3f", nx, ny, nz)
            uv += struct.pack("<2f", u, v)
            xs.append(px)
            ys.append(py)
            zs.append(pz)
        idx += struct.pack("<3H", n, n + 1, n + 2)
        n += 3
    bin_blob = b""
    views = []

    def add_view(data, target):
        nonlocal bin_blob
        bin_blob = pad4(bin_blob)
        off = len(bin_blob)
        view = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        bin_blob += data
        return len(views) - 1

    pv = add_view(pos, 34962)
    nv = add_view(nor, 34962)
    tv = add_view(uv, 34962)
    iv = add_view(idx, 34963)
    im = add_view(png_bytes, None)
    acc = [
        {"bufferView": pv, "componentType": 5126, "count": n, "type": "VEC3",
         "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
        {"bufferView": nv, "componentType": 5126, "count": n, "type": "VEC3"},
        {"bufferView": tv, "componentType": 5126, "count": n, "type": "VEC2"},
        {"bufferView": iv, "componentType": 5123, "count": n, "type": "SCALAR"},
    ]
    gltf = {
        "asset": {"version": "2.0", "generator": "mk4-pc-geo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": label, "mesh": 0}],
        "meshes": [{"name": label, "primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3,
            "material": 0,
        }]}],
        "materials": [{
            "name": "mk4",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0,
                "roughnessFactor": 1,
            },
        }],
        "textures": [{"source": 0}],
        "images": [{"bufferView": im, "mimeType": "image/png"}],
        "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}],
        "accessors": acc,
        "bufferViews": views,
        "buffers": [{"byteLength": len(pad4(bin_blob))}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    blob = pad4(bin_blob)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack("<I", len(js)) + b"JSON" + js
    out += struct.pack("<I", len(blob)) + b"BIN\x00" + blob
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(out)
    return len(out), (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def render(tris, tex, path):
    """Front view and side view, textured, so the shape can be checked."""
    pts = [c[0] for t in tris for c in t]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    views = (
        ("front", 0, 1, 2),  # x, y, depth z
        ("side", 2, 1, 0),   # z, y, depth x
    )
    tw, th = tex.size
    tpx = tex.load()
    panels = []
    for name, ia, ib, ic in views:
        span_a = max(xs if ia == 0 else zs) - min(xs if ia == 0 else zs) or 1
        # Use the real axes.
        aval = [p[ia] for p in pts]
        bval = [p[ib] for p in pts]
        cval = [p[ic] for p in pts]
        a0, a1 = min(aval), max(aval)
        b0, b1 = min(bval), max(bval)
        pad = 8
        w, h = 420, 640
        img = Image.new("RGB", (w, h), (18, 18, 22))
        depth = [1e9] * (w * h)
        pix = img.load()
        scale = min((w - 2 * pad) / (a1 - a0 or 1), (h - 2 * pad) / (b1 - b0 or 1))

        def proj(p):
            sx = pad + (p[ia] - a0) * scale
            sy = pad + (b1 - p[ib]) * scale
            return sx, sy, p[ic]

        order = sorted(range(len(tris)), key=lambda i: sum(tris[i][k][0][ic] for k in range(3)))
        for ti in order:
            tri = tris[ti]
            p0, p1, p2 = (proj(c[0]) for c in tri)
            uvs = [c[1] for c in tri]
            minx = max(0, int(min(p0[0], p1[0], p2[0])))
            maxx = min(w - 1, int(max(p0[0], p1[0], p2[0])) + 1)
            miny = max(0, int(min(p0[1], p1[1], p2[1])))
            maxy = min(h - 1, int(max(p0[1], p1[1], p2[1])) + 1)
            area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
            if abs(area) < 1e-6:
                continue
            for y in range(miny, maxy + 1):
                for x in range(minx, maxx + 1):
                    w0 = (p1[0] - x) * (p2[1] - y) - (p2[0] - x) * (p1[1] - y)
                    w1 = (p2[0] - x) * (p0[1] - y) - (p0[0] - x) * (p2[1] - y)
                    w2 = (p0[0] - x) * (p1[1] - y) - (p1[0] - x) * (p0[1] - y)
                    if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                        w0, w1, w2 = w0 / area, w1 / area, w2 / area
                        z = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
                        di = y * w + x
                        if z < depth[di]:
                            depth[di] = z
                            u = w0 * uvs[0][0] + w1 * uvs[1][0] + w2 * uvs[2][0]
                            v = w0 * uvs[0][1] + w1 * uvs[1][1] + w2 * uvs[2][1]
                            # stored v was flipped for glTF; the PNG is top-down
                            tx = int(u * (tw - 1)) % tw
                            ty = int((1.0 - v) * (th - 1)) % th
                            pix[x, y] = tpx[tx, ty]
        panels.append(img)
    sheet = Image.new("RGB", (420 * 2 + 8, 640), (0, 0, 0))
    sheet.paste(panels[0], (0, 0))
    sheet.paste(panels[1], (428, 0))
    sheet.save(path)


def load_named(fs, disc_name):
    h = fsys_hash(PREFIX + disc_name)
    for i in range(799):
        hh, off, size = struct.unpack_from("<III", fs, i * 12)
        if hh == h:
            return fs[off:off + size], i, size
    raise SystemExit("missing " + disc_name)


def mesh_blocks(blocks):
    """Fighters: the type-1 set. Files without type 1 (logos 0x4, arenas, effects): every 3D part."""
    if any(b["type"] == 1 for b in blocks):
        return [b for b in blocks if b["type"] == 1]
    return blocks


def atlas_pages(textures, tris):
    """If the triangles use more than one texture page, stack the pages vertically and remap the UVs."""
    used = sorted({c[2] for t in tris for c in t})
    if len(used) <= 1 or max(used) >= len(textures):
        tex = textures[used[0]] if used and used[0] < len(textures) else textures[0]
        return tex, tris
    W = max(t.size[0] for t in textures)
    H = sum(t.size[1] for t in textures)
    atlas = Image.new("RGB", (W, H))
    yoff = []
    y = 0
    for t in textures:
        atlas.paste(t, (0, y))
        yoff.append(y)
        y += t.size[1]
    out = []
    for t in tris:
        nt = []
        for xyz, (u, v), page in t:
            pw, ph = textures[page].size
            nu = u * pw / W
            nv = 1.0 - (yoff[page] + (1.0 - v) * ph) / H
            nt.append((xyz, (nu, nv), page))
        out.append(nt)
    return atlas, out


def export_one(fs, disc_name):
    blob, idx, size = load_named(fs, disc_name)
    tex_off, blocks = parse_blocks(blob)
    textures = decode_rle555(blob, tex_off)
    tris = []
    for block in mesh_blocks(blocks):
        tris.extend(triangles_of(blob, block))
    if not tris:
        raise SystemExit("no 3D parts in " + disc_name)
    tex, tris = atlas_pages(textures, tris)
    textures = [tex] + textures[1:]
    label = ROSTER.get(disc_name, disc_name.rsplit(".", 1)[0].lower())
    os.makedirs(OUT, exist_ok=True)
    tex_path = os.path.join(OUT, label + "_tex.png")
    textures[0].save(tex_path)
    import io
    buf = io.BytesIO()
    textures[0].save(buf, format="PNG")
    glb_path = os.path.join(OUT, label + ".glb")
    nbytes, box = write_glb(glb_path, tris, buf.getvalue(), label)
    prev = os.path.join(OUT, label + "_preview.png")
    render(tris, textures[0], prev)
    slots = {}
    for tri in tris:
        slots[tri[0][2]] = slots.get(tri[0][2], 0) + 1
    print(label, "idx", idx, "file", size, "tex", len(textures), textures[0].size,
          "tris", len(tris), "glb", nbytes)
    print("  box", " ".join("%.2f" % v for v in box))
    print("  pages", slots, " part types", sorted({b["type"] for b in mesh_blocks(blocks)}))
    print("  ", glb_path)
    print("  ", prev)
    return glb_path, prev, tex_path


def write_parts_glb(path, part_tris, png_bytes, label):
    """One node per part, set on a grid so the pieces do not overlap."""
    bin_blob = b""
    views = []
    accessors = []
    meshes = []
    nodes = []

    def add_view(data, target):
        nonlocal bin_blob
        bin_blob = pad4(bin_blob)
        off = len(bin_blob)
        view = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        bin_blob += data
        return len(views) - 1

    cols = 6
    cell = 2.4
    for pi, tris in enumerate(part_tris):
        raw = [c[0] for t in tris for c in t]
        cx = sum(p[0] for p in raw) / len(raw) / 100.0
        cy = sum(p[1] for p in raw) / len(raw) / 100.0
        cz = sum(p[2] for p in raw) / len(raw) / 100.0
        ox = (pi % cols) * cell - cx
        oy = - (pi // cols) * cell - cy
        oz = -cz
        pos = b""
        nor = b""
        uv = b""
        idx = b""
        xs, ys, zs = [], [], []
        n = 0
        for tri in tris:
            pts = [c[0] for c in tri]
            ax, ay, az = pts[0]
            bx, by, bz = pts[1]
            cx_, cy_, cz_ = pts[2]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx_ - ax, cy_ - ay, cz_ - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
            nx, ny, nz = nx / length, ny / length, nz / length
            for (x, y, z), (u, v), _slot in tri:
                px = x / 100.0 + ox
                py = y / 100.0 + oy
                pz = z / 100.0 + oz
                pos += struct.pack("<3f", px, py, pz)
                nor += struct.pack("<3f", nx, ny, nz)
                uv += struct.pack("<2f", u, v)
                xs.append(px)
                ys.append(py)
                zs.append(pz)
            idx += struct.pack("<3H", n, n + 1, n + 2)
            n += 3
        pv = add_view(pos, 34962)
        nv = add_view(nor, 34962)
        tv = add_view(uv, 34962)
        iv = add_view(idx, 34963)
        pa = len(accessors)
        accessors.append({
            "bufferView": pv, "componentType": 5126, "count": n, "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)],
        })
        accessors.append({"bufferView": nv, "componentType": 5126, "count": n, "type": "VEC3"})
        accessors.append({"bufferView": tv, "componentType": 5126, "count": n, "type": "VEC2"})
        accessors.append({"bufferView": iv, "componentType": 5123, "count": n, "type": "SCALAR"})
        meshes.append({"name": "part_%02d" % pi, "primitives": [{
            "attributes": {"POSITION": pa, "NORMAL": pa + 1, "TEXCOORD_0": pa + 2},
            "indices": pa + 3, "material": 0,
        }]})
        nodes.append({"name": "part_%02d" % pi, "mesh": len(meshes) - 1})
    im = add_view(png_bytes, None)
    child = list(range(1, len(nodes) + 1))
    nodes.insert(0, {"name": label, "children": child})
    gltf = {
        "asset": {"version": "2.0", "generator": "mk4-pc-geo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [{
            "name": "mk4",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0,
                "roughnessFactor": 1,
            },
        }],
        "textures": [{"source": 0}],
        "images": [{"bufferView": im, "mimeType": "image/png"}],
        "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(pad4(bin_blob))}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    blob = pad4(bin_blob)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack("<I", len(js)) + b"JSON" + js
    out += struct.pack("<I", len(blob)) + b"BIN\x00" + blob
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(out)
    return len(out)


def export_parts(fs, disc_name):
    import io
    blob, idx, size = load_named(fs, disc_name)
    tex_off, blocks = parse_blocks(blob)
    textures = decode_rle555(blob, tex_off)
    groups = []
    for block in blocks:
        if block["type"] != 1:
            continue
        groups.append(triangles_of(blob, block))
    label = ROSTER.get(disc_name, disc_name.rsplit(".", 1)[0].lower())
    os.makedirs(OUT, exist_ok=True)
    textures[0].save(os.path.join(OUT, label + "_tex.png"))
    buf = io.BytesIO()
    textures[0].save(buf, format="PNG")
    glb_path = os.path.join(OUT, label + "_parts.glb")
    nbytes = write_parts_glb(glb_path, groups, buf.getvalue(), label)
    tris = sum(len(g) for g in groups)
    print("%s  idx %d  parts %d  tris %d  tex %s  %d bytes  %s" % (
        label, idx, len(groups), tris, textures[0].size, nbytes, glb_path))
    return glb_path


def main():
    global PATH, OUT
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    PATH, OUT = sys.argv[1], sys.argv[2]
    fs = open(PATH, "rb").read()
    want = sys.argv[3:] or ["SZ_GEO.GEO"]
    if want == ["ALL"]:
        for name in ROSTER:
            export_parts(fs, name)
        return
    for name in want:
        export_one(fs, name)


if __name__ == "__main__":
    main()
