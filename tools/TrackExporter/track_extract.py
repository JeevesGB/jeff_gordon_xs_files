#!/usr/bin/env python3
"""
Export the TRACK MODELS of Jeff Gordon XS Racing as textured OBJ/MTL files.

    python track_extract.py GAME.ART  track_models                 # every S*.RSS in the archive
    python track_extract.py Gamel.art track_models --split --yup
    python track_extract.py S711.RSS  track_models --textures textures_png     # one RSS + already-decoded PNGs

Needs rss_extract.py (same folder, or ../ARTExtract): it unpacks the .ART, decodes the textures and reads the RSS files with the
loader-exact walker. The track models are the S*.RSS files in the ART (S711, SACCEL, SCLOVER, SDROPZN, SFRITO,
SFUTURE, SGAMBLR, SINDUST, SNEON, SPLANET, SPPSI2K, SSKIDPAD). SINDUSTT and SPLANETT are separate parts of their tracks.

Per RSS file the output folder holds
    <NAME>.obj + <NAME>.mtl   the whole model, one OBJ group per game object, textured (UVs already mapped into the full PNG)
    textures/                 only the PNGs this model uses
    <NAME>.driving_line.obj   the type-1 "dl" objects as polylines (when the file has them)
    objects/                  (--split) one OBJ per game object
    <NAME>.summary.json       object/face counts, extents, textures used and any problems
Units are the game's own (inches; --metres for metres). Axes are the file's Z-up unless --yup is given.
Not exported: per-vertex colours (some SFUTURE surfaces), transparency (palette entry 0 is probably a colour key), lighting.
"""
import argparse, json, re, shutil, struct, sys, tempfile
from pathlib import Path
_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent / "ARTExtract"):            # rss_extract.py next to this file, or in tools/ARTExtract
    if (_d / "rss_extract.py").exists(): sys.path.insert(0, str(_d)); break
else: sys.exit("rss_extract.py not found next to this script or in ..\\ARTExtract")
import rss_extract as R

def safe(s): return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "unnamed"

def export_track(rss, tex_dir, out, split=False, yup=False):
    d = Path(rss).read_bytes(); name = Path(rss).stem.upper(); out.mkdir(parents=True, exist_ok=True)
    summary = {"model": name, "source_bytes": len(d), "problems": []}
    groups, _ = R.parse_material_table(d)
    walk = R.walk_objects(d); meshes = R.meshes_from_walk(walk)
    by_label = {}
    for g in groups: by_label.setdefault(g["label"], g)
    mat_names = R.material_names(groups)
    # textures: copy only what this model's surfaces name
    avail = {p.stem.casefold(): p for p in Path(tex_dir).glob("*.png")} if tex_dir else {}
    tex_files, missing = {}, set()
    for g in groups:
        for s in (g["children"] or [g]):
            t = s["texture"]
            if not t: continue
            p = avail.get(t.casefold())
            if p is None: missing.add(t); continue
            (out / "textures").mkdir(exist_ok=True); shutil.copyfile(p, out / "textures" / p.name)
            tex_files[t.casefold()] = f"textures/{p.name}"
    R.write_mtl(out / f"{name}.mtl", groups, mat_names, tex_files)
    items, per_object, unresolved = [], {}, 0
    for m in meshes:
        g = by_label.get(m["name"])
        if g is None: summary["problems"].append(f"object {m['object']!r}: material group {m['name']!r} not in the table"); continue
        it = (f"{m['object']}.{m['name']}", m["vertex_sets"][0], m["faces"], g)
        items.append(it); per_object.setdefault(m["object"], []).append(it)
    unresolved = R.write_textured_obj(out / f"{name}.obj", f"{name}.mtl", items, mat_names, yup=yup)
    if split:
        (out / "objects").mkdir(exist_ok=True)
        for i, (oname, its) in enumerate(per_object.items()):
            R.write_textured_obj(out / "objects" / f"{i:03d}_{safe(oname)}.obj", f"../{name}.mtl", its, mat_names, yup=yup)
    dls = R.write_driving_lines(out, name, walk)       # writes into 'out' (same folder as the model)
    allv = [v for _, vs, _, _ in items for v in vs]
    ext = None
    if allv:
        ext = {"min": [min(v[k] for v in allv) for k in range(3)], "max": [max(v[k] for v in allv) for k in range(3)]}
    summary.update({"objects": len(walk["objects"]), "mesh_objects": sum(1 for o in walk["objects"] if o["type"] == 0),
                    "submeshes": len(meshes), "vertices": sum(len(v) for _, v, _, _ in items),
                    "faces": sum(len(f) for _, _, f, _ in items), "faces_without_surface": unresolved,
                    "vertex_colour_submeshes": sum(1 for m in meshes if m["has_colour"]),
                    "textures_used": sorted(p.name for p in (out / "textures").glob("*.png")) if (out / "textures").exists() else [],
                    "textures_missing": sorted(missing), "driving_lines": dls, "extent": ext,
                    "units": "inches" if R.POS_SCALE > 0.0003 else "metres", "axes": "Y-up" if yup else "Z-up (file)"})
    if missing: summary["problems"].append(f"{len(missing)} texture(s) named in the table have no PNG")
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help=".ART archive, or an .RSS file")
    ap.add_argument("out_dir", nargs="?", default="track_models")
    ap.add_argument("--textures", help="folder of decoded PNGs (only needed for a bare .RSS; an .ART decodes its own)")
    ap.add_argument("--all", action="store_true", help="export every RSS in the ART, cars included (default: S*.RSS only)")
    ap.add_argument("--split", action="store_true", help="also write one OBJ per game object in objects/")
    ap.add_argument("--yup", action="store_true", help="convert to Y-up: (x, y, z) -> (x, z, -y)")
    ap.add_argument("--metres", action="store_true", help="write metres instead of the game's inches")
    a = ap.parse_args(); t = Path(a.target); out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    if a.metres: R.POS_SCALE *= 0.0254
    tmp = None
    if t.is_file() and R.is_art(t):
        tmp = Path(tempfile.mkdtemp(prefix="trk_art_"))
        rss_list, manifest, warns = R.unpack_art(t, tmp / "rss", tmp / "textures_png")
        for w in warns: print("warning:", w)
        tex_dir = tmp / "textures_png"
        print(f"{t.name}: {len(rss_list)} RSS files, {sum('png' in r for r in manifest)}/{len(manifest)} textures decoded")
        if not a.all: rss_list = [p for p in rss_list if p.stem.upper().startswith("S")]
    else:
        rss_list, tex_dir = [t], a.textures
        if not tex_dir: print("note: no --textures folder, materials will be flat grey")
    done = []
    for p in rss_list:
        try:
            s = export_track(p, tex_dir, out / p.stem.upper(), a.split, a.yup); done.append(s)
            print(f"{s['model']:10} {s['mesh_objects']:4} objects {s['submeshes']:4} submeshes {s['faces']:6} faces  "
                  f"{len(s['textures_used'])} textures  {len(s['driving_lines'])} driving lines"
                  + (f"  PROBLEMS: {s['problems']}" if s["problems"] else ""))
        except (ValueError, struct.error, IndexError) as e:
            print(f"{p.name}: FAILED ({type(e).__name__}: {e})")
    (out / "all_models_summary.json").write_text(json.dumps(done, indent=2), encoding="utf-8")
    if tmp: shutil.rmtree(tmp, ignore_errors=True)
    print(f"Finished: {len(done)} model(s) -> {out}")

if __name__ == "__main__": main()