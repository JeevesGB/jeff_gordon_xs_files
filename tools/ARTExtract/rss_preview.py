#!/usr/bin/env python3
"""
Software-render a textured preview of an fRssExport V1 .RSS model, to check the
texture mapping documented in rssmat.py / TEXTURE_MAPPING.md.

    python3 rss_preview.py ALIEN.RSS textures_png out.png [--view top|side|rear|iso]
                           [--mesh N] [--all-lods] [--pose 0|1] [--size 900x700]

Needs numpy + Pillow, plus rss_extract.py (find_meshes) and rssmat.py next to this file.
Textures are the PNGs written by `rss_extract.py GAME.ART out_dir` (textures_png/).
Surfaces whose texture has no PNG are drawn mid-grey; untextured surfaces use the flat
colour stored in the first 3 bytes of the surface record.
"""
import argparse, math, os, re, sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rss_extract as R
import rssmat

VIEWS = {"top": (0, 0), "side": (90, -90), "rear": (0, -90), "iso": (-40, -62)}

def f16(v): return (v if v < 2**31 else v - 2**32) / 65536.0

class Textures:
    def __init__(self, folder):
        self.map = {p.stem.casefold(): p for p in Path(folder).glob("*.png")}; self.cache = {}
    def get(self, name):
        k = (name or "").casefold()
        if k not in self.cache:
            self.cache[k] = np.asarray(Image.open(self.map[k]).convert("RGB")) if k in self.map else None
        return self.cache[k]

def collect(path, only_mesh=None, all_lods=False, pose=0):
    """Triangles: (3 x [x,y,z,u,v], surface_record, mesh_index, flag)."""
    d = Path(path).read_bytes()
    groups, _ = rssmat.parse_table(d); labels = {}
    for g in groups: labels.setdefault(g["label"], g)
    tris = []
    try: meshes = R.meshes_from_walk(R.walk_objects(d))     # exact loader-based walk
    except (ValueError, IndexError): meshes = R.find_meshes(d)    # heuristic fallback
    for mi, b in enumerate(meshes):
        if not b["vertex_sets"]: continue            # no recovered vertex array -> not drawable
        if only_mesh is not None and mi != only_mesh: continue
        if not all_lods and re.search(r"(_[1-9]|[1-9])$", b["name"]): continue
        if not all_lods and "shadow" in b["name"].lower(): continue
        g = labels.get(b["name"])
        if g is None: continue
        V = b["vertex_sets"][min(pose, len(b["vertex_sets"]) - 1)]
        for verts, flag, _ in b["faces"]:
            s = rssmat.surface(g, flag)
            if s is None: continue
            pts = [(*V[i], f16(a[3]), f16(a[4])) for i, a in verts if i < len(V)]
            for k in range(1, len(pts) - 1): tris.append((pts[0], pts[k], pts[k + 1], s, mi, flag))
    return tris

def render(tris, textures, W=900, H=700, yaw=-40, pitch=-62):
    ya, pa = math.radians(yaw), math.radians(pitch)
    Rz = np.array([[math.cos(ya), -math.sin(ya), 0], [math.sin(ya), math.cos(ya), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(pa), -math.sin(pa)], [0, math.sin(pa), math.cos(pa)]])
    P = np.array([[t[i][:3] for i in range(3)] for t in tris]) @ (Rx @ Rz).T
    sc = 0.85 * min(W / (np.ptp(P[..., 0]) + 1e-9), H / (np.ptp(P[..., 1]) + 1e-9))
    cx, cy = (P[..., 0].max() + P[..., 0].min()) / 2, (P[..., 1].max() + P[..., 1].min()) / 2
    img = np.full((H, W, 3), 30, np.uint8); zb = np.full((H, W), -1e18)
    for ti, t in enumerate(tris):
        pc = P[ti]; sx = (pc[:, 0] - cx) * sc + W / 2; sy = H / 2 - (pc[:, 1] - cy) * sc; z = pc[:, 2]
        x0, x1 = int(max(0, math.floor(sx.min()))), int(min(W - 1, math.ceil(sx.max())))
        y0, y1 = int(max(0, math.floor(sy.min()))), int(min(H - 1, math.ceil(sy.max())))
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        den = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
        if abs(den) < 1e-9: continue
        l0 = ((sy[1] - sy[2]) * (xs - sx[2]) + (sx[2] - sx[1]) * (ys - sy[2])) / den
        l1 = ((sy[2] - sy[0]) * (xs - sx[2]) + (sx[0] - sx[2]) * (ys - sy[2])) / den
        l2 = 1 - l0 - l1
        m = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
        if not m.any(): continue
        zz = l0 * z[0] + l1 * z[1] + l2 * z[2]; sub = zb[y0:y1 + 1, x0:x1 + 1]; vis = m & (zz > sub)
        if not vis.any(): continue
        s = t[3]; tx = textures.get(s["texture"]) if s["texture"] else None
        if tx is None:
            body = bytes.fromhex(s["body_hex"]); flat = body[:3] if not s["texture"] else b"\x80\x80\x80"
            col = np.empty(vis.shape + (3,), np.uint8); col[:] = np.frombuffer(flat, np.uint8)
        else:
            u = np.clip(l0 * t[0][3] + l1 * t[1][3] + l2 * t[2][3], 0, 1)
            v = np.clip(l0 * t[0][4] + l1 * t[1][4] + l2 * t[2][4], 0, 1)
            ru, rv, rw, rh = s["rect"]                      # <- the mapping, see rssmat.texel_xy
            px = np.clip(((ru + u * rw) * tx.shape[1]).astype(int), 0, tx.shape[1] - 1)
            py = np.clip(((rv + (1 - v) * rh) * tx.shape[0]).astype(int), 0, tx.shape[0] - 1)
            col = tx[py, px]
        img[y0:y1 + 1, x0:x1 + 1][vis] = col[vis]; sub[vis] = zz[vis]
    return Image.fromarray(img)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rss"); ap.add_argument("textures_png"); ap.add_argument("out_png")
    ap.add_argument("--view", choices=VIEWS, default="iso"); ap.add_argument("--mesh", type=int)
    ap.add_argument("--all-lods", action="store_true"); ap.add_argument("--pose", type=int, default=0)
    ap.add_argument("--size", default="900x700")
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.lower().split("x"))
    tris = collect(a.rss, a.mesh, a.all_lods, a.pose)
    if not tris: raise SystemExit("nothing drawable (no mesh with a recovered vertex array matched the material table)")
    yaw, pitch = VIEWS[a.view]
    render(tris, Textures(a.textures_png), W, H, yaw, pitch).save(a.out_png)
    print(f"{a.rss}: {len(tris)} triangles -> {a.out_png}")

if __name__ == "__main__": main()
