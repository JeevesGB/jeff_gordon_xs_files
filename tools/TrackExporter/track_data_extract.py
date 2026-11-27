#!/usr/bin/env python3
"""
Extractor for the per-track data files of Jeff Gordon XS Racing (original/tracks/<track>/<track>.tr?).

    python track_extract.py original/tracks track_out
    python track_extract.py original/tracks/s711/s711.trs track_out

Files are grouped by their base name (the folder is ignored: sgamblr.* and sindust.* currently sit in sfuture/).
Every container layout below was checked by consuming each file EXACTLY to its last byte (the "exact" flag in
<track>.summary.json). Field MEANINGS are hypotheses unless stated; columns are named for what the values look
like, not for what the game does with them. The game's own loaders for these files have not been read yet.

  .trs  sounds     u16 0, u16 n, n * { name\\0, u16, 7 * i32 }          (30 bytes after each name)
                   -> positional sound emitters: WAV name, (x, height?, z), two ranges. VERIFIED layout, guessed meaning.
  .trc  28-byte    u16 0, u16 n, n * { 6 * i32, u16 kind, u16 0 }       likely two 3D points + a kind (1 or 2)
  .trl  56-byte    u16 2, u16 n, n * 14 * i32                           mixed fields, not understood (raw words kept)
  .trk  lines      u16 1, u16 nlines, per line: u16 n, n * { u16 100, i32 flag(0/16), i32 -120, i32 -2400, i32 2400 }
                   nlines equals the number of type-1 "dl" objects in the track's RSS (S711, SACCEL, SCLOVER, SDROPZN, SFRITO,
                   SFUTURE, SGAMBLR, SNEON, SPPSI2K and SPLANETT all match; SINDUST has none and no .trk)
                   -> per-sample parameters along a driving line (constant columns look like lane/width limits).
  .trt  terrain?   u16 0, u16 n, 6 float32 (bounding box), then data NOT decoded. Seen: 112-byte records holding the
                   u32 value 2, and runs of ~256 consecutive floats (a 16x16 grid?). The loader (Terrain.c in the game's
                   strings) is needed to decode it; only header + bounding box + a raw word dump are written.
"""
import argparse, csv, json, struct, sys, zlib
from pathlib import Path

EXT = (".trs", ".trc", ".trl", ".trk", ".trt")

def rd(b, p, fmt):
    v = struct.unpack_from(fmt, b, p); return v, p + struct.calcsize(fmt)

def parse_trs(b):
    (zero, n), p = rd(b, 0, "<HH"); rows = []
    for i in range(n):
        e = b.index(b"\0", p); name = b[p:e].decode("cp1252"); p = e + 1
        f, p = rd(b, p, "<Hiiiiiii")
        rows.append(dict(index=i, sound=name, flag=f[0], param_32000=f[1], x=f[2], y=f[3], z=f[4], range_a=f[5], range_b=f[6], last=f[7]))
    return {"header": {"u16_0": zero, "count": n}, "rows": rows}, p

def parse_trc(b):
    (zero, n), p = rd(b, 0, "<HH"); rows = []
    for i in range(n):
        f, p = rd(b, p, "<6iHH")
        rows.append(dict(index=i, p0x=f[0], p0y=f[1], p0z=f[2], p1x=f[3], p1y=f[4], p1z=f[5], kind=f[6], pad=f[7]))
    return {"header": {"u16_0": zero, "count": n}, "rows": rows}, p

def parse_trl(b):
    (ver, n), p = rd(b, 0, "<HH"); rows = []
    for i in range(n):
        f, p = rd(b, p, "<14i"); rows.append({"index": i, **{f"w{k}": v for k, v in enumerate(f)}})
    return {"header": {"version": ver, "count": n}, "rows": rows}, p

def parse_trk(b):
    (ver, nl), p = rd(b, 0, "<HH"); lines = []
    for li in range(nl):
        (n,), p = rd(b, p, "<H"); rows = []
        for i in range(n):
            f, p = rd(b, p, "<Hiiii")
            rows.append(dict(line=li, index=i, const_100=f[0], flag=f[1], c_m120=f[2], c_m2400=f[3], c_2400=f[4]))
        lines.append(rows)
    return {"header": {"version": ver, "lines": nl, "points_per_line": [len(l) for l in lines]},
            "rows": [r for l in lines for r in l]}, p

def parse_trt(b):
    (zero, n), p = rd(b, 0, "<HH"); bbox, p = rd(b, p, "<6f")
    words = struct.unpack_from(f"<{(len(b) - p) // 4}I", b, p)
    twos = [p + 4 * i for i, w in enumerate(words) if w == 2 and i >= 1 and (i + 28) < len(words) and words[i + 28] == 2]
    return {"header": {"u16_0": zero, "count": n, "bbox_min_xyz": bbox[:3], "bbox_max_xyz": bbox[3:], "size": len(b)},
            "undecoded_bytes": len(b) - p, "marker_offsets_value2_every_112_bytes": twos[:64]}, None  # not consumed

PARSERS = {".trs": parse_trs, ".trc": parse_trc, ".trl": parse_trl, ".trk": parse_trk, ".trt": parse_trt}

def write_csv(path, rows):
    if not rows: return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def process_track(stem, files, out):
    out.mkdir(parents=True, exist_ok=True); summary = {"track": stem, "files": {}}
    for f in sorted(files, key=lambda x: x.suffix):
        b = f.read_bytes(); ext = f.suffix.lower(); info = {"source": str(f), "size": len(b), "crc32": f"{zlib.crc32(b):08x}"}
        try:
            data, end = PARSERS[ext](b)
            info["exact"] = (end == len(b)) if end is not None else None     # None = layout only partly known
            info.update({"header": data["header"]})
            if "rows" in data:
                write_csv(out / f"{stem}{ext}.csv", data["rows"]); info["rows"] = len(data["rows"])
                info["csv"] = f"{stem}{ext}.csv"
            else:
                (out / f"{stem}{ext}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                info["json"] = f"{stem}{ext}.json"; info["undecoded_bytes"] = data["undecoded_bytes"]
            if end is not None and end != len(b): info["note"] = f"parser stopped at {end} of {len(b)} bytes"
        except Exception as e:
            info["exact"] = False; info["error"] = f"{type(e).__name__}: {e}"
        summary["files"][ext] = info
    (out / f"{stem}.summary.json").write_text(json.dumps(summary, indent=2, default=list), encoding="utf-8")
    return summary

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a track file (.trs/.trc/.trl/.trk/.trt) or a folder searched recursively")
    ap.add_argument("out_dir", nargs="?", default="track_extracted")
    a = ap.parse_args(); t = Path(a.target)
    files = [t] if t.is_file() else sorted(p for p in t.rglob("*") if p.is_file() and p.suffix.lower() in EXT)
    if not files: sys.exit("no track files found")
    groups = {}
    for f in files: groups.setdefault(f.stem.lower(), []).append(f)
    allsum = []
    for stem, fs in sorted(groups.items()):
        s = process_track(stem, fs, Path(a.out_dir) / stem); allsum.append(s)
        print(f"{stem:10} " + "  ".join(f"{e[1:]}:{'ok' if i.get('exact') else ('partial' if i.get('exact') is None and 'error' not in i else 'FAIL')}"
                                        for e, i in sorted(s["files"].items())))
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    (Path(a.out_dir) / "all_tracks_summary.json").write_text(json.dumps(allsum, indent=2, default=list), encoding="utf-8")
    print(f"Finished: {len(groups)} tracks, {len(files)} files -> {a.out_dir}")

if __name__ == "__main__": main()
