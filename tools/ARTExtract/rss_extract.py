from __future__ import annotations
import argparse, csv, hashlib, json, math, os, re, shutil, struct, zipfile, zlib
from pathlib import Path

TEXT_EXT = rb'(?:bmp|tga|pcx|png|jpe?g|dds|raw|pal|wav|bin|dat|anm|skl|msh|rss|ini|txt|cfg|fnt|iff|tif|tiff|gif)'
SIGNATURES = {
    "PNG": b"\x89PNG\r\n\x1a\n", "JPEG": b"\xff\xd8\xff",
    "BMP": b"BM", "GIF87a": b"GIF87a", "GIF89a": b"GIF89a",
    "RIFF": b"RIFF", "WAVE": b"WAVE", "Ogg": b"OggS",
    "ZIP": b"PK\x03\x04", "DDS": b"DDS ", "TGA-like": b"\x00\x00\x02\x00",
    "PCX": b"\x0a", "ID3": b"ID3",
}
def sha256(data): return hashlib.sha256(data).hexdigest()
def fixed16(v):
    """16.16 fixed point. Accepts the raw u32 word and treats it as signed (two's complement)."""
    return (v - 4294967296 if v >= 2147483648 else v) / 65536.0

def parse_mesh_block(data, pos):
    """Conservative recogniser for the mesh layout hypothesised by the old script."""
    if pos + 15 > len(data): return None
    nf = struct.unpack_from("<H", data, pos)[0]
    if not 1 <= nf <= 4000 or data[pos+2] != 0: return None
    hdr = struct.unpack_from("<3I", data, pos+3)
    off, faces = pos+15, []
    for _ in range(nf):
        if off+2 > len(data): return None
        n = struct.unpack_from("<H", data, off)[0]
        if not 3 <= n <= 8: return None
        off += 2; vertices = []
        for _ in range(n):
            if off+22 > len(data): return None
            idx = struct.unpack_from("<H", data, off)[0]
            attrs = struct.unpack_from("<5I", data, off+2)
            vertices.append((idx, attrs)); off += 22
        if off+14 > len(data): return None
        flag = struct.unpack_from("<H", data, off)[0]
        extra = struct.unpack_from("<3I", data, off+2)
        off += 14; faces.append((vertices, flag, extra))
    return {"nfaces": nf, "hdr": hdr, "faces": faces, "start": pos, "end": off}

def find_meshes(data):
    found = []
    for m in re.finditer(rb"[A-Za-z][A-Za-z0-9_ /.-]{1,63}\x00", data):
        block = parse_mesh_block(data, m.end())
        if not block: continue
        block["name"] = m.group()[:-1].decode("cp1252", "replace")
        block["name_offset"] = m.start()
        block["max_index"] = max(v[0] for f in block["faces"] for v in f[0])
        found.append(block)
    previous_end = 0
    for b in found:
        b["vertex_sets"] = []
        count = b["max_index"] + 1
        for nsets in (2, 1):
            start = b["name_offset"] - nsets * count * 12
            if start < 4: continue
            n0, n1 = struct.unpack_from("<HH", data, start-4)
            if (n0, n1) == (nsets, count) or start == previous_end:
                for k in range(nsets):
                    arr = [tuple(fixed16(x) for x in struct.unpack_from("<3i", data, start+(k*count+i)*12))
                           for i in range(count)]
                    b["vertex_sets"].append(arr)
                b["vertex_span"] = [start, b["name_offset"]]
                break
        previous_end = b["end"]
    return found

def write_obj(path, name, verts, faces):
    uvmap, uvs = {}, []
    for face, _flag, _extra in faces:
        for idx, attrs in face:
            uv=(fixed16(attrs[3]),fixed16(attrs[4]))
            if uv not in uvmap:
                uvmap[uv]=len(uvs)+1
                uvs.append(uv)
    safe_name=re.sub(r"\W+", "_", name)
    lines=[f"# Heuristically decoded mesh: {name}",
           f"o {safe_name}"]
    lines += [f"v {x:.7f} {y:.7f} {z:.7f}" for x,y,z in verts]
    lines += [f"vt {u:.7f} {v:.7f}" for u,v in uvs]
    for face, _flag, _extra in faces:
        tokens=[]
        for idx,attrs in face:
            uv=(fixed16(attrs[3]),fixed16(attrs[4]))
            tokens.append(f"{idx+1}/{uvmap[uv]}")
        lines.append("f "+" ".join(tokens))
    Path(path).write_text("\n".join(lines)+"\n",encoding="utf-8")


def runs_ascii(data, minlen=3):
    return [{"offset":m.start(),"length":len(m.group()),"text":m.group().decode("cp1252","replace")}
            for m in re.finditer(rb"[\x20-\x7e]{"+str(minlen).encode()+rb",}",data)]
def runs_utf16(data, minchars=3):
    out=[]
    for parity in (0,1):
        pattern=rb"(?:[\x20-\x7e]\x00){"+str(minchars).encode()+rb",}"
        for m in re.finditer(pattern,data[parity:]):
            start=parity+m.start()
            out.append({"offset":start,"length":len(m.group()),"text":m.group().decode("utf-16le","replace")})
    return sorted(out,key=lambda x:x["offset"])
def embedded_refs(data):
    pat=rb"[\x20-\x7e]{1,160}\."+TEXT_EXT+rb"(?=[\x00\x20-\x7e])"
    return [{"offset":m.start(),"value":m.group().decode("ascii","replace")}
            for m in re.finditer(pat,data,re.I)]
def signature_hits(data):
    hits=[]
    for label,sig in SIGNATURES.items():
        pos=0
        while True:
            pos=data.find(sig,pos)
            if pos<0: break
            hits.append({"type":label,"offset":pos,"signature_hex":sig.hex()}); pos+=1
    return sorted(hits,key=lambda x:x["offset"])
def entropy(data):
    if not data: return 0.0
    counts=[0]*256
    for b in data: counts[b]+=1
    n=len(data)
    return -sum((c/n)*math.log2(c/n) for c in counts if c)
def entropy_windows(data, window=256):
    return [{"offset":i,"length":len(data[i:i+window]),"entropy":round(entropy(data[i:i+window]),4)}
            for i in range(0,len(data),window)]
def complement_ranges(size, spans):
    spans=sorted((max(0,s),min(size,e)) for s,e in spans if e>s)
    merged=[]
    for s,e in spans:
        if not merged or s>merged[-1][1]: merged.append([s,e])
        else: merged[-1][1]=max(merged[-1][1],e)
    gaps=[]; cur=0
    for s,e in merged:
        if s>cur: gaps.append((cur,s))
        cur=max(cur,e)
    if cur<size: gaps.append((cur,size))
    return gaps


def _valid_png(data, off):
    if data[off:off+8] != b"\x89PNG\r\n\x1a\n" or off+33 > len(data): return None
    if data[off+12:off+16] != b"IHDR": return None
    w,h=struct.unpack_from(">II",data,off+16)
    if not (1<=w<=16384 and 1<=h<=16384): return None
    import zlib
    pos=off+8
    while pos+12<=len(data):
        n=struct.unpack_from(">I",data,pos)[0]
        typ=data[pos+4:pos+8]
        end=pos+12+n
        if n>len(data) or end>len(data): return None
        crc_expected=struct.unpack_from(">I",data,pos+8+n)[0]
        if (zlib.crc32(data[pos+4:pos+8+n]) & 0xffffffff) != crc_expected: return None
        pos=end
        if typ==b"IEND": return pos-off if n==0 else None
    return None

def _valid_gif(data, off):
    if data[off:off+6] not in (b"GIF87a",b"GIF89a") or off+13>len(data): return None
    w,h=struct.unpack_from("<HH",data,off+6)
    if not (1<=w<=16384 and 1<=h<=16384): return None

    end=data.find(b";",off+13,min(len(data),off+64*1024*1024))
    return end+1-off if end>=0 else None

def _valid_bmp(data, off):
    if data[off:off+2]!=b"BM" or off+54>len(data): return None
    size=struct.unpack_from("<I",data,off+2)[0]
    pix=struct.unpack_from("<I",data,off+10)[0]
    dib=struct.unpack_from("<I",data,off+14)[0]
    if dib<40 or size<14+dib or off+size>len(data) or pix<14+dib or pix>=size: return None
    w,h=struct.unpack_from("<ii",data,off+18)
    planes,bpp=struct.unpack_from("<HH",data,off+26)
    if not (1<=w<=16384 and 1<=abs(h)<=16384 and planes==1 and bpp in (1,4,8,16,24,32)): return None
    return size

def _valid_dds(data, off):
    if data[off:off+4]!=b"DDS " or off+128>len(data): return None
    size,height,width=struct.unpack_from("<III",data,off+4)
    if size!=124 or not(1<=width<=16384 and 1<=height<=16384): return None

    return None

def _valid_jpeg(data, off):
    if data[off:off+2] != b"\xff\xd8" or off+4 > len(data): return None
    pos=off+2
    saw_frame=False

    for _ in range(10000):
        if pos>=len(data) or data[pos] != 0xff: return None
        while pos<len(data) and data[pos]==0xff: pos+=1
        if pos>=len(data): return None
        marker=data[pos]; pos+=1
        if marker==0xd9: return pos-off if saw_frame else None
        if marker==0xda:
            if not saw_frame or pos+2>len(data): return None
            seglen=struct.unpack_from(">H",data,pos)[0]
            if seglen<2 or pos+seglen>len(data): return None
            end=data.find(b"\xff\xd9",pos+seglen)
            return end+2-off if end>=0 else None
        if marker in (0x01,) or 0xd0<=marker<=0xd7: continue
        if pos+2>len(data): return None
        seglen=struct.unpack_from(">H",data,pos)[0]
        if seglen<2 or pos+seglen>len(data): return None
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            if seglen<7: return None
            h,w=struct.unpack_from(">HH",data,pos+3)
            if not(1<=w<=16384 and 1<=h<=16384): return None
            saw_frame=True
        pos+=seglen
    return None

def _valid_pcx(data, off):
    if off+128>len(data) or data[off]!=0x0a: return None
    h=data[off:off+128]
    ver,enc,bpp=h[1],h[2],h[3]
    xmin,ymin,xmax,ymax=struct.unpack_from("<4H",h,4)
    planes=h[65]; bpl=struct.unpack_from("<H",h,66)[0]
    w=xmax-xmin+1; hh=ymax-ymin+1
    if ver not in (0,2,3,4,5) or enc not in (0,1) or bpp not in (1,2,4,8): return None
    if not(1<=w<=8192 and 1<=hh<=8192 and planes in (1,2,3,4) and 0<bpl<=8192): return None
    if bpl<((w*bpp+7)//8): return None

    need=bpl*planes*hh; pos=off+128; produced=0
    while pos<len(data) and produced<need:
        b=data[pos]; pos+=1
        if enc==1 and (b&0xc0)==0xc0:
            if pos>=len(data): return None
            count=b&0x3f
            if count==0: return None
            pos+=1; produced+=count
        else: produced+=1
        if produced>need+8192: return None
    if produced<need: return None
    return pos-off

def extract_embedded_images(data, outdir, min_size=32):
    out=Path(outdir)
    validators=[
        ("png","PNG",lambda d,o:_valid_png(d,o)),
        ("jpg","JPEG",lambda d,o:_valid_jpeg(d,o)),
        ("bmp","BMP",lambda d,o:_valid_bmp(d,o)),
        ("gif","GIF",lambda d,o:_valid_gif(d,o)),
        ("pcx","PCX",lambda d,o:_valid_pcx(d,o)),
    ]
    candidates=[]
    for ext,kind,validator in validators:
        sig={"png":b"\x89PNG\r\n\x1a\n","jpg":b"\xff\xd8","bmp":b"BM",
             "gif":(b"GIF87a",b"GIF89a"),"pcx":b"\x0a"}[ext]
        sigs=sig if isinstance(sig,tuple) else (sig,)
        for signature in sigs:
            pos=0
            while True:
                off=data.find(signature,pos)
                if off<0: break
                pos=off+1
                length=validator(data,off)
                if length and length>=min_size:
                    candidates.append({"offset":off,"length":length,"format":kind,"extension":ext})
    candidates.sort(key=lambda x:(x["offset"],-x["length"]))
    selected=[]
    for c in candidates:
        if any(c["offset"] < x["offset"]+x["length"] and
               x["offset"] < c["offset"]+c["length"] for x in selected):
            continue
        selected.append(c)
    if selected:
        out.mkdir(parents=True,exist_ok=True)
    for i,c in enumerate(selected):
        name=f"texture_{i:04d}_0x{c['offset']:08x}.{c['extension']}"
        (out/name).write_bytes(data[c["offset"]:c["offset"]+c["length"]])
        c["file"]=name
        c["sha256"]=sha256(data[c["offset"]:c["offset"]+c["length"]])
    return selected


def nul_strings(data):
    out=[]
    for m in re.finditer(rb'[\x20-\x7e]{2,100}\x00', data):
        value=m.group()[:-1].decode("ascii","replace")
        out.append({"offset":m.start(),"end":m.end(),"value":value})
    return out

def discover_texture_names(data):

    ss=nul_strings(data)
    found=[]
    for i,x in enumerate(ss):
        value=x["value"]
        if i == 0 or x["offset"] > 65536:
            continue
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{3,31}',value):
            continue
        prev=ss[i-1]
        gap=x["offset"]-prev["offset"]
        if not 35 <= gap <= 65:
            continue

        if len(prev["value"]) < 4 or not re.search(r'[A-Za-z]',prev["value"]):
            continue
        if 35 <= (ss[i+1]["offset"]-x["offset"]) <= 65 if i+1<len(ss) else False:
            continue
        found.append({
            "name":value,
            "offset":x["offset"],
            "evidence":"surface_label_then_texture_identifier",
            "surface_labels":[prev["value"]],
            "occurrences":1
        })
    unique={}
    for x in found:
        key=x["name"].casefold()
        if key not in unique:
            unique[key]={**x,"occurrences_at_offsets":[x["offset"]]}
        else:
            unique[key]["occurrences"]+=1
            unique[key]["occurrences_at_offsets"].append(x["offset"])
            if x["surface_labels"][0] not in unique[key]["surface_labels"]:
                unique[key]["surface_labels"].append(x["surface_labels"][0])
    return list(unique.values())


def build_asset_index(paths):
    index={}
    for p in paths:
        p=Path(p)
        if not p.is_file() or p.suffix.lower()==".rss":
            continue
        index.setdefault(p.stem.casefold(),[]).append(p)
    return index

def write_texture_manifest(refs, texture_dir, asset_index=None):

    td=Path(texture_dir)
    td.mkdir(parents=True,exist_ok=True)
    asset_index=asset_index or {}
    records=[]
    for i,ref in enumerate(refs):
        name=ref["name"]
        stem=Path(name).stem.casefold()
        matches=asset_index.get(stem,[])
        copied=[]
        for j,src in enumerate(matches):
            # Avoid copying unrelated configuration or another RSS container.
            if src.suffix.lower() not in {
                ".bmp",".tga",".pcx",".png",".jpg",".jpeg",".dds",
                ".gif",".tif",".tiff",".raw",".pal",".dat",".bin"
            }:
                continue
            dest=td/(src.name if len(matches)==1 else f"{src.stem}_{j}{src.suffix}")
            if not dest.exists():
                shutil.copy2(src,dest)
            copied.append(dest.name)
        rec={**ref,"asset_status":"found_and_copied" if copied else "reference_only_no_pixel_asset_found",
             "copied_files":copied}
        records.append(rec)
        if not copied:
            safe=re.sub(r'[^A-Za-z0-9_.-]+','_',name)[:60] or f"texture_{i}"
            note=td/f"{safe}.reference.txt"
            if not note.exists():
                note.write_text(
                    f"RSS texture reference: {name}\n"
                    f"RSS byte offset: 0x{ref['offset']:08x}\n"
                    f"Detection evidence: {ref['evidence']}\n"
                    f"Associated surface labels: {', '.join(ref['surface_labels']) or '(not identified)'}\n\n"
                    "No matching pixel/image asset was present in the supplied archive or asset search path.\n"
                    "This file is a reference record, NOT an image. The RSS stores a texture identifier here;\n"
                    "the actual bitmap may be a separate game asset or use a proprietary encoding.\n",
                    encoding="utf-8")
    (td/"texture_manifest.json").write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf-8")
    with (td/"texture_manifest.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["name","offset","evidence","surface_labels","occurrences",
                                       "asset_status","copied_files"],extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({**r,"surface_labels":"; ".join(r["surface_labels"]),
                        "copied_files":"; ".join(r["copied_files"])})
    found=sum(r["asset_status"]=="found_and_copied" for r in records)
    (td/"README.txt").write_text(
        "RSS texture extraction report\n"
        "==============================\n"
        f"Unique texture identifiers (from the RSS material table; heuristic scan only if no table parsed): {len(records)}\n"
        f"Matching external image/texture files copied: {found}\n"
        f"Identifiers with no matching pixel asset: {len(records)-found}\n\n"
        "Important: an RSS texture identifier is not the texture bitmap.\n"
        "When no matching image file is available, the .reference.txt files\n"
        "record the names and offsets; they are not fake or blank textures.\n"
        "The supplied input (ZIP, ART archive or folder) was searched for matching external assets.\n",
        encoding="utf-8")
    return records

def is_art(path):
    try:
        with open(path, "rb") as f: return f.read(4) == b"Art\x00"
    except OSError:
        return False

def read_art_directory(data):
    if len(data) < 32 or data[:4] != b"Art\x00": raise ValueError("not an ART container")
    count, declared = struct.unpack_from("<II", data, 0x18)
    warnings = []
    if declared != len(data):
        warnings.append(f"size field {declared} != file size {len(data)}")
    entries = []
    for i in range(1, count):
        o = i * 32
        if o + 32 > len(data):
            warnings.append(f"directory truncated at entry {i}"); break
        name = data[o:o+23].split(b"\0")[0].decode("cp1252", "replace")
        typ = data[o+23]
        off, size = struct.unpack_from("<II", data, o + 24)
        if off + size > len(data):
            warnings.append(f"entry {i} ({name!r}) points outside the file; skipped"); continue
        entries.append({"index": i, "name": name, "type": typ, "offset": off, "size": size})
    return entries, warnings

def _lzw_decode(data, start, minbits=8):
    clear = 1 << minbits; eoi = clear + 1
    size = minbits + 1; nxt = eoi + 1
    table = {i: bytes([i]) for i in range(clear)}
    out = bytearray(); prev = None; buf = 0; nb = 0; pos = start
    while True:
        while nb < size and pos < len(data):
            buf |= data[pos] << nb; nb += 8; pos += 1
        if nb < size: return bytes(out), "truncated"
        code = buf & ((1 << size) - 1); buf >>= size; nb -= size
        if code == clear:
            size = minbits + 1; nxt = eoi + 1
            table = {i: bytes([i]) for i in range(clear)}; prev = None; continue
        if code == eoi: return bytes(out), "eoi"
        if prev is None:
            if code not in table: return bytes(out), "bad-first-code"
            ent = table[code]
        else:
            if code in table: ent = table[code]
            elif code == nxt: ent = table[prev] + table[prev][:1]
            else: return bytes(out), f"bad-code-{code}"
            if nxt < 4096:
                table[nxt] = table[prev] + ent[:1]; nxt += 1
                if nxt == (1 << size) and size < 12: size += 1
        out += ent; prev = code

def decode_texture(blob):
    if len(blob) < 9 + 768: raise ValueError("too short for header + palette")
    kind = blob[0]
    x, y, w, h = struct.unpack_from("<4H", blob, 1)
    if not (1 <= w <= 8192 and 1 <= h <= 8192): raise ValueError(f"implausible size {w}x{h}")
    if kind == 0x71:
        if 9 + w*h + 768 != len(blob): raise ValueError("raw size mismatch")
        idx, codec = blob[9:9+w*h], "raw"
    elif kind == 0x51:
        idx, why = _lzw_decode(blob, 9)
        if why != "eoi" or len(idx) != w*h: raise ValueError(f"lzw {why}, {len(idx)}/{w*h} pixels")
        codec = "lzw"
    else:
        raise ValueError(f"unknown type byte 0x{kind:02x}")
    return {"width": w, "height": h, "x_field": x, "y_field": y, "indices": idx,
            "palette": blob[-768:], "codec": codec}

def _png_rgb(w, h, rgb):
    raw = b"".join(b"\0" + rgb[r*w*3:(r+1)*w*3] for r in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

def unpack_art(art_path, unpack_dir, png_dir):

    data = Path(art_path).read_bytes()
    entries, warnings = read_art_directory(data)
    unpack_dir, png_dir = Path(unpack_dir), Path(png_dir)
    unpack_dir.mkdir(parents=True, exist_ok=True)
    rss_paths, manifest, used = [], [], {}
    for e in entries:
        blob = data[e["offset"]:e["offset"]+e["size"]]
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", e["name"]).strip(" .") or f"entry{e['index']}"
        if e["type"] == 0x44:
            dest = unpack_dir / safe
            dest.write_bytes(blob)
            if dest.suffix.lower() == ".rss": rss_paths.append(dest)
            continue
        rec = {"index": e["index"], "name": e["name"], "type_byte": e["type"],
               "archive_offset": e["offset"], "size": e["size"], "sha256": sha256(blob)}
        try:
            img = decode_texture(blob)
            pal = img["palette"]
            rgb = b"".join(pal[i*3:i*3+3] for i in img["indices"])
            png_dir.mkdir(parents=True, exist_ok=True)
            n = used.get(safe.casefold(), 0); used[safe.casefold()] = n + 1
            fn = f"{safe}.png" if n == 0 else f"{safe}_dup{n}.png"
            (png_dir / fn).write_bytes(_png_rgb(img["width"], img["height"], rgb))
            rec.update({"png": fn, "codec": img["codec"], "width": img["width"], "height": img["height"],
                        "x_field": img["x_field"], "y_field": img["y_field"],
                        "palette_entry0_rgb": list(pal[:3])})
        except ValueError as err:
            rec["decode_error"] = str(err)
        manifest.append(rec)
    return sorted(rss_paths), manifest, warnings

_MAT_LABEL = re.compile(rb"[A-Za-z0-9][\x20-\x7e]{0,60}\x00")

def _material_record_at(d, p):
    try:
        m = _MAT_LABEL.match(d, p)
        if not m or d[m.end()+6:m.end()+9] != b"\xe5\xe5\xe5": return None
        q = m.end() + 39
        rec = {"label": m.group()[:-1].decode("cp1252"), "offset": p, "body_hex": d[m.end():q].hex(),
               "texture": None, "texture_offset": None, "rect": None, "children": []}
        if 0x20 <= d[q] < 0x7f:
            e = d.index(b"\0", q)
            rec["texture"] = d[q:e].decode("cp1252"); rec["texture_offset"] = q; q = e + 1
            rec["rect"] = tuple(x / 32768.0 for x in struct.unpack_from("<4I", d, q)); q += 16
        rec["nchild"] = struct.unpack_from("<H", d, q)[0]
        return rec, q + 2
    except (ValueError, IndexError, struct.error):
        return None

def parse_material_table(d):
    p = d.find(b"\n") + 1
    start = next((s for s in range(p, p + 32) if _material_record_at(d, s)), None)
    if start is None: raise ValueError("no material records found")
    groups, p = [], start
    while True:
        r = _material_record_at(d, p)
        if not r: break
        rec, p = r
        for _ in range(rec["nchild"]):
            c = _material_record_at(d, p)
            if not c: raise ValueError(f"child record of {rec['label']!r} missing at 0x{p:x}")
            child, p = c; rec["children"].append(child)
        groups.append(rec)
    return groups, p

def material_surface(group, flag):
    kids = group["children"]
    if kids: return kids[flag] if flag < len(kids) else None
    return group if flag == 0 else None

def texture_refs_from_table(groups):
    uniq = {}
    for g in groups:
        for s in (g["children"] or [g]):
            if not s["texture"]: continue
            r = uniq.setdefault(s["texture"].casefold(), {
                "name": s["texture"], "offset": s["texture_offset"], "evidence": "material_table_surface",
                "surface_labels": [], "occurrences": 0, "occurrences_at_offsets": [], "rects": []})
            r["occurrences"] += 1; r["occurrences_at_offsets"].append(s["texture_offset"])
            if s["label"] not in r["surface_labels"]: r["surface_labels"].append(s["label"])
            r["rects"].append({"group": g["label"], "surface": s["label"], "rect_u_v_w_h": list(s["rect"])})
    return list(uniq.values())

def material_names(groups):
    names, used = {}, {}
    for g in groups:
        for s in (g["children"] or [g]):
            raw = g["label"] if s is g else f"{g['label']}__{s['label']}"
            nm = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "material"
            n = used.get(nm.casefold(), 0); used[nm.casefold()] = n + 1
            names[id(s)] = nm if n == 0 else f"{nm}_{n}"
    return names

def write_mtl(path, groups, mat_names, tex_files):
    lines = ["# Materials from the RSS material table (one per surface).",
             "# Texture coordinates in the OBJ files are already transformed into the full texture;",
             "# see TEXTURE_MAPPING.md for the mapping."]
    for g in groups:
        for s in (g["children"] or [g]):
            body = bytes.fromhex(s["body_hex"])
            tex = tex_files.get((s["texture"] or "").casefold())
            kd = (1.0, 1.0, 1.0) if tex else tuple(c / 255.0 for c in body[:3]) if not s["texture"] else (0.5, 0.5, 0.5)
            lines += ["", f"newmtl {mat_names[id(s)]}",
                      f"# group={g['label']!r} surface={s['label']!r} texture={s['texture']!r} rect={s['rect']}",
                      "Ka 1.0 1.0 1.0", "Kd %.4f %.4f %.4f" % kd, "d 1.0", "illum 1"]
            if tex: lines.append(f"map_Kd {tex}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_textured_obj(path, mtl_name, items, mat_names):
    lines = [f"# Textured mesh(es) decoded heuristically from an fRssExport V1 file", f"mtllib {mtl_name}"]
    uvmap, uvs, voff, unresolved = {}, [], 0, 0
    body = []
    for oname, verts, faces, group in items:
        body.append(f"o {re.sub(r'[^A-Za-z0-9_.-]+', '_', oname)}")
        body += [f"v {x:.7f} {y:.7f} {z:.7f}" for x, y, z in verts]
        cur = None
        for face, flag, _extra in faces:
            surf = material_surface(group, flag)
            if surf is None: unresolved += 1
            if surf is not None and mat_names[id(surf)] != cur:
                cur = mat_names[id(surf)]; body.append(f"usemtl {cur}")
            toks = []
            for idx, attrs in face:
                u, v = fixed16(attrs[3]), fixed16(attrs[4])
                if surf is not None and surf["rect"]:
                    ru, rv, rw, rh = surf["rect"]
                    u, v = ru + u * rw, 1.0 - (rv + (1.0 - v) * rh)     
                key = (round(u, 7), round(v, 7))
                if key not in uvmap: uvmap[key] = len(uvs) + 1; uvs.append(key)
                toks.append(f"{voff + idx + 1}/{uvmap[key]}")
            body.append("f " + " ".join(toks))
        voff += len(verts)
        if cur is None: body.append("# (no material assigned in this object)")
    lines += [f"vt {u:.7f} {v:.7f}" for u, v in uvs]
    Path(path).write_text("\n".join(lines + body) + "\n", encoding="utf-8")
    return unresolved


def analyse(path, outdir, carve=True, hex_dump=False, texture_min_size=32, asset_index=None):
    data=Path(path).read_bytes()
    out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
    base=Path(path).stem
    (out/f"{base}.original.rss").write_bytes(data)
    nl=data.find(b"\n"); header_end=nl+1 if nl>=0 else 0
    header=data[:nl if nl>=0 else min(len(data),256)].decode("cp1252","replace").rstrip("\r")

    try:
        groups,table_end=parse_material_table(data); table_error=None
    except ValueError as err:
        groups,table_end,table_error=None,None,str(err)
    textures=extract_embedded_images(data,out/"textures"/"embedded_images",min_size=texture_min_size)
    texture_refs=texture_refs_from_table(groups) if groups else discover_texture_names(data)
    texture_assets=write_texture_manifest(texture_refs,out/"textures",asset_index)
    tex_files={r["name"].casefold():"textures/"+r["copied_files"][0] for r in texture_assets if r["copied_files"]}
    group_by_label={}
    mat_names={}
    if groups:
        for g in groups: group_by_label.setdefault(g["label"],g)
        mat_names=material_names(groups)
        write_mtl(out/f"{base}.mtl",groups,mat_names,tex_files)
    textured_files=[]; mesh_links=[]
    meshes=find_meshes(data)
    mesh_summaries=[]
    mesh_spans=[]
    for i,b in enumerate(meshes):
        name=re.sub(r"[^A-Za-z0-9_-]+","_",b["name"]).strip("_") or f"mesh{i}"
        item={"index":i,"name":b["name"],"name_offset":b["name_offset"],"face_span":[b["start"],b["end"]],
              "face_count":b["nfaces"],"max_vertex_index":b["max_index"],
              "vertex_span":b.get("vertex_span"),"vertex_set_count":len(b["vertex_sets"]),
              "vertex_count":len(b["vertex_sets"][0]) if b["vertex_sets"] else None,
              "header_words":list(b["hdr"])}
        mesh_summaries.append(item); mesh_spans.append((b["start"],b["end"]))
        if b.get("vertex_span"):
            mesh_spans.append(tuple(b["vertex_span"]))
        for k,verts in enumerate(b["vertex_sets"]):
            write_obj(out/f"{base}.mesh{i:03d}.{name}.set{k}.obj",b["name"],verts,b["faces"])
        grp=group_by_label.get(b["name"])
        if groups is not None:
            link={"mesh_index":i,"name":b["name"],"has_vertex_array":bool(b["vertex_sets"]),
                  "material_group_found":grp is not None,"faces_without_surface":None}
            if grp is not None and b["vertex_sets"]:
                for k,verts in enumerate(b["vertex_sets"]):
                    fn=f"{base}.mesh{i:03d}.{name}.set{k}.textured.obj"
                    miss=write_textured_obj(out/fn,f"{base}.mtl",[(b["name"],verts,b["faces"],grp)],mat_names)
                    textured_files.append(fn); link["faces_without_surface"]=miss
            mesh_links.append(link)
        (out/f"{base}.mesh{i:03d}.face_block.bin").write_bytes(data[b["start"]:b["end"]])

        face_meta=[]
        for face_index,(vertices,flag,extra) in enumerate(b["faces"]):
            face_meta.append({
                "face_index":face_index,
                "flag_raw":flag,
                "extra_u32_raw":list(extra),
                "vertices":[{"vertex_index":idx,"attributes_u32_raw":list(attrs),
                             "uv_fixed16":[fixed16(attrs[3]),fixed16(attrs[4])],
                             "unit_vector_x0p5_fixed16":[fixed16(attrs[0]),fixed16(attrs[1]),fixed16(attrs[2])]}
                            for idx,attrs in vertices]
            })
        (out/f"{base}.mesh{i:03d}.{name}.mesh_data.json").write_text(
            json.dumps({"mesh_name":b["name"],"header_words":list(b["hdr"]),
                        "face_records":face_meta},indent=2),encoding="utf-8")
    gaps=complement_ranges(len(data),[(0,header_end)]+mesh_spans)
    gap_records=[]
    if carve:
        gd=out/"unclaimed_ranges"; gd.mkdir(exist_ok=True)
        for i,(s,e) in enumerate(gaps):
            fn=f"range_{i:04d}_0x{s:08x}_0x{e:08x}.bin"
            (gd/fn).write_bytes(data[s:e])
            gap_records.append({"index":i,"start":s,"end":e,"size":e-s,"file":fn})
    else:
        gap_records=[{"index":i,"start":s,"end":e,"size":e-s} for i,(s,e) in enumerate(gaps)]
    if groups:
        linked=[(i,b,group_by_label[b["name"]]) for i,b in enumerate(meshes) if b["vertex_sets"] and b["name"] in group_by_label]
        for k in range(max((len(b["vertex_sets"]) for _,b,_ in linked),default=0)):
            items=[(f"{b['name']}_mesh{i:03d}",b["vertex_sets"][k],b["faces"],g)
                   for i,b,g in linked if len(b["vertex_sets"])>k]
            fn=f"{base}.all_meshes.set{k}.textured.obj"
            write_textured_obj(out/fn,f"{base}.mtl",items,mat_names); textured_files.append(fn)
    material_table=None if groups is None else {
        "table_end_offset":table_end,"group_count":len(groups),
        "surface_count":sum(len(g["children"]) or 1 for g in groups),
        "groups":[{"label":g["label"],"offset":g["offset"],"texture":g["texture"],
                   "rect_u_v_w_h":g["rect"],"body_hex":g["body_hex"],
                   "surfaces":[{"index":j,"label":s["label"],"offset":s["offset"],"texture":s["texture"],
                                "rect_u_v_w_h":list(s["rect"]) if s["rect"] else None,"body_hex":s["body_hex"]}
                               for j,s in enumerate(g["children"])]} for g in groups]}
    strings=runs_ascii(data)
    wide=runs_utf16(data)
    refs=embedded_refs(data)
    report={
      "file":Path(path).name,"size":len(data),"sha256":sha256(data),"header":header,
      "header_bytes_hex":data[:header_end].hex(),"mesh_parser_note":"Heuristic only; not a complete documented RSS specification.",
      "material_table":material_table,"material_table_error":table_error,
      "material_table_note":"Texture mapping, reverse-engineered: face flag -> surface -> texture + 1.15 fixed-point rect; "
                            "face UVs are local to the rect (v up). Textured OBJs carry the transformed UVs. See TEXTURE_MAPPING.md.",
      "mesh_material_links":mesh_links,"textured_obj_files":textured_files,
      "meshes":mesh_summaries,"embedded_image_files":textures,"texture_references":texture_assets,"texture_extraction_note":"The RSS files contain probable texture identifiers/material references. Validated standard embedded images are exported separately; external matching assets are copied when present. Reference records are not image data.",
      "ascii_strings":strings,"utf16le_strings":wide,
      "embedded_filename_references":refs,"embedded_signatures":signature_hits(data),
      "entropy_256_byte_windows":entropy_windows(data),"unclaimed_ranges":gap_records,
      "coverage":{"source_bytes":len(data),"raw_copy_bytes":len(data),
                  "bytes_in_recognised_mesh_spans":sum(e-s for s,e in
                      [(a,b) for a,b in sorted(mesh_spans)]),
                  "bytes_in_unclaimed_ranges":sum(e-s for s,e in gaps),
                  "note":"All source bytes are retained in the .original.rss copy; unclaimed ranges are separately carved."}
    }
    (out/f"{base}.report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/f"{base}.strings.txt").write_text(
        "ASCII STRINGS (byte offsets)\n"+ "\n".join(f"0x{x['offset']:08x} [{x['length']}] {x['text']}" for x in strings)+
        "\n\nUTF-16LE STRINGS (byte offsets)\n"+ "\n".join(f"0x{x['offset']:08x} [{x['length']}] {x['text']}" for x in wide),
        encoding="utf-8")
    if hex_dump:
        with open(out/f"{base}.hex.txt","w",encoding="ascii") as f:
            for i in range(0,len(data),16):
                chunk=data[i:i+16]
                f.write(f"{i:08x}  {' '.join(f'{b:02x}' for b in chunk):47}  "+
                        "".join(chr(b) if 32<=b<127 else "." for b in chunk)+"\n")
    print(f"{Path(path).name}: {len(data)} bytes, {len(meshes)} mesh candidates, "
          f"{len(strings)} ASCII strings, {len(wide)} UTF-16 strings, {len(textures)} embedded images, {len(texture_refs)} texture references, {len(gaps)} unclaimed ranges, "
          + (f"material table: {material_table['group_count']} groups/{material_table['surface_count']} surfaces, "
             f"{len(textured_files)} textured OBJ" if material_table else f"no material table ({table_error})"))
    return report

def main():
    ap=argparse.ArgumentParser(description="Lossless forensic extractor for fRssExport V1 .RSS files")
    ap.add_argument("target",help="RSS file, directory, ZIP archive, or .ART archive (RSS files are extracted and textures decoded to PNG)")
    ap.add_argument("out_dir",nargs="?",default="rss_extracted")
    ap.add_argument("--no-carve",action="store_true",help="Do not write unclaimed byte ranges")
    ap.add_argument("--hex",action="store_true",help="Write a complete offset-labelled hex dump (large)")
    ap.add_argument("--keep-unpacked",action="store_true",help="Keep unpacked ZIP/ART contents (including JGRACING.INI from an ART) in output")
    ap.add_argument("--texture-min-size",type=int,default=32,help="Minimum bytes for a carved image (default: 32)")
    ap.add_argument("--asset-root",help="Additional folder to search for external texture files")
    args=ap.parse_args()
    target=Path(args.target); out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    inputs=[]
    art_mode=target.is_file() and is_art(target)
    if art_mode:
        inputs,tex_manifest,art_warnings=unpack_art(target,out/"_art_contents",out/"textures_png")
        for msg in art_warnings: print(f"warning: {msg}")
        (out/"art_texture_manifest.json").write_text(json.dumps(tex_manifest,indent=2,ensure_ascii=False),encoding="utf-8")
        decoded=sum("png" in r for r in tex_manifest)
        print(f"{target.name}: {len(inputs)} RSS files, {decoded}/{len(tex_manifest)} textures decoded to PNG"
              + (f", {len(tex_manifest)-decoded} failed (see art_texture_manifest.json)" if decoded!=len(tex_manifest) else ""))
    elif target.is_file() and zipfile.is_zipfile(target):
        unpack=out/"_zip_contents"
        unpack.mkdir(exist_ok=True)
        with zipfile.ZipFile(target) as z:
            for info in z.infolist():
                if info.is_dir(): continue
                dest=(unpack/info.filename).resolve()
                if unpack.resolve() not in dest.parents and dest != unpack.resolve():
                    raise ValueError(f"Unsafe ZIP member path: {info.filename}")
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(z.read(info))
                if dest.suffix.lower()==".rss": inputs.append(dest)
    elif target.is_file():
        if target.suffix.lower()!=".rss": raise SystemExit("Input file must be .RSS, an .ART archive or a ZIP archive")
        inputs=[target]
    elif target.is_dir():
        inputs=sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower()==".rss")
    else: raise SystemExit(f"Input not found: {target}")
    if not inputs: raise SystemExit("No .RSS files found")
    asset_paths=[]
    if art_mode:
        asset_paths=[p for p in (out/"textures_png").rglob("*") if p.is_file()] if (out/"textures_png").is_dir() else []
    elif target.is_file() and zipfile.is_zipfile(target):
        asset_paths=[p for p in (out/"_zip_contents").rglob("*") if p.is_file()]
    elif target.is_dir():
        asset_paths=[p for p in target.rglob("*") if p.is_file()]
    else:
        asset_paths=[target]
    if args.asset_root:
        asset_paths += [p for p in Path(args.asset_root).rglob("*") if p.is_file()]
    asset_index=build_asset_index(asset_paths)
    summaries=[]
    all_texture_refs=[]
    for p in inputs:
        rep=analyse(p,out/p.stem,carve=not args.no_carve,hex_dump=args.hex,texture_min_size=args.texture_min_size,asset_index=asset_index)
        for tref in rep["texture_references"]:
            all_texture_refs.append({"rss_file":rep["file"],**tref})
        summaries.append({"file":rep["file"],"size":rep["size"],"sha256":rep["sha256"],
                          "mesh_candidates":len(rep["meshes"]),"embedded_texture_files":len(rep["embedded_image_files"]),
                          "texture_references":len(rep["texture_references"]),
                          "material_groups":(rep["material_table"] or {}).get("group_count"),
                          "material_surfaces":(rep["material_table"] or {}).get("surface_count"),
                          "textured_obj_files":len(rep["textured_obj_files"]),"ascii_strings":len(rep["ascii_strings"]),
                          "utf16le_strings":len(rep["utf16le_strings"]),
                          "unclaimed_bytes":rep["coverage"]["bytes_in_unclaimed_ranges"]})
    (out/"archive_summary.json").write_text(json.dumps(summaries,indent=2),encoding="utf-8")
    (out/"texture_reference_catalog.json").write_text(
        json.dumps(all_texture_refs,indent=2,ensure_ascii=False),encoding="utf-8")
    if art_mode and not args.keep_unpacked:
        shutil.rmtree(out/"_art_contents")
    elif target.is_file() and zipfile.is_zipfile(target) and not args.keep_unpacked:
        shutil.rmtree(out/"_zip_contents")
    print(f"Finished: {len(inputs)} RSS files -> {out.resolve()}")
if __name__=="__main__": main()