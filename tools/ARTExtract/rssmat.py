"""
Material/surface table of fRssExport V1 (.RSS) files.  Reverse-engineered, not documented.

The table sits between the header line and the first mesh block.  It is a sequence of
records; a record that has children is followed by exactly that many child records:

    label           NUL-terminated string (e.g. "Alien Front_0")
    body[39]        bytes 6..8 are always e5 e5 e5 (used as the record signature); bytes 0..5
                    vary (ff.. / ad.. - probably colours); bytes 9..14 are 00 20 00 00 66 06 or
                    zeros; the rest is NOT decoded
    -- leaf only: next byte is printable --
    texture         NUL-terminated texture name == name of an entry in the .ART (e.g. "Alien")
    rect[4]         u32 x4 = u, v, w, h as 1.15 fixed point (value / 32768), measured in
                    fractions of the texture, v from the TOP row   [verified: max u+w and
                    v+h is exactly 0.5 for all 94 texture groups in Gamel.art]
    nchild          u16 number of child records that follow

Top-level groups are named like the meshes that use them ("Alien_0", "car shadow").
Within a mesh face record the u16 "flag" is the 0-based index into the group's children
(or 0 for a group that is itself a single leaf).
Face vertex UVs are 16.16 fixed point, local to the surface (0..1 across the rect), with
v pointing UP.  Texel position in the PNG:
        x = (rect.u + u * rect.w) * width
        y = (rect.v + (1 - v) * rect.h) * height
"""
import re, struct

SIG = b"\xe5\xe5\xe5"      # body[6:9]; body[0:6] varies (ff.. / ad..: colours?)
LABEL = re.compile(rb"[A-Za-z0-9][\x20-\x7e]{0,60}\x00")

def _record_at(d, p):
    """Parse one record at p, or return None if the signature is not there."""
    m = LABEL.match(d, p)
    if not m or d[m.end() + 6:m.end() + 9] != SIG: return None
    label = m.group()[:-1].decode("cp1252"); q = m.end() + 39
    rec = {"label": label, "offset": p, "body_hex": d[m.end():q].hex(),
           "texture": None, "rect": None, "children": []}
    if 0x20 <= d[q] < 0x7f:
        e = d.index(b"\0", q); rec["texture"] = d[q:e].decode("cp1252"); q = e + 1
        rec["rect"] = tuple(x / 32768.0 for x in struct.unpack_from("<4I", d, q)); q += 16
    rec["nchild"] = struct.unpack_from("<H", d, q)[0]
    return rec, q + 2

def parse_table(d):
    """Return (groups, end_offset). groups = list of top-level records with .children filled."""
    p = d.find(b"\n") + 1
    # first record: scan the few header counter bytes for the first valid record
    start = None
    for s in range(p, p + 32):
        if _record_at(d, s): start = s; break
    if start is None: raise ValueError("no material records found")
    groups, p = [], start
    while True:
        r = _record_at(d, p)
        if not r: break
        rec, p = r
        for _ in range(rec["nchild"]):
            c = _record_at(d, p)
            if not c: raise ValueError(f"child of {rec['label']!r} missing at 0x{p:x}")
            child, p = c; rec["children"].append(child)
        groups.append(rec)
    return groups, p

def surface(group, flag):
    """Resolve a face's flag to its surface record (leaf with texture+rect)."""
    kids = group["children"]      # the game uses children[flag % nchildren]; a childless group is itself the surface
    return kids[flag % len(kids)] if kids else group

def texel_xy(surf, u, v, tex_w, tex_h):
    """Map a local face-vertex UV (v up) to texel coordinates (origin top-left)."""
    ru, rv, rw, rh = surf["rect"]
    return (ru + u * rw) * tex_w, (rv + (1.0 - v) * rh) * tex_h
