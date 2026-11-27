# ARTExtract

Extractor for fRssExport (V1) .RSS files and the game's .ART archives.

Input may be a game .ART archive (GAME.ART, Gamel.art), a single .RSS, a folder or a ZIP. RSS files are unpacked
verbatim, textures (Q/q entries) are decoded to PNG, and every RSS file is parsed **exactly as the game loads it**
(`walk_objects`, written from the decompiled loader; it reads all 42 RSS files of both archives to the last byte).
The old heuristic mesh scan is only a fallback. File layout: `RSS_FORMAT.md`. Texture mapping: `TEXTURE_MAPPING.md`.

## Usage
```
python rss_extract.py GAME.ART GAME.ART_out
python rss_extract.py Gamel.art Gamel.art_out [--metres] [--no-carve] [--asset-root DIR]
python rss_preview.py ALIEN.RSS GAME.ART_out/textures_png alien.png --view iso      # software-rendered check (needs numpy, Pillow)
```
Track models have their own tool: `..\TrackExporter`.

## Output per RSS file (`<out>/<NAME>/`)
```
<NAME>.original.rss, .report.json, .strings.txt, .mtl      textures/   unclaimed_ranges/
obj/            plain OBJ per submesh and pose (v, vt, vn)
obj_textured/   textured OBJ per submesh + <NAME>.all_meshes.setN.textured.obj  (mtllib ../<NAME>.mtl)
json/           per-submesh face data        bin/   raw submesh bytes        obj/*.driving_line.*.obj  (type-1 "dl" objects)
```
Positions are in the game's units (inches, file Z-up); `--metres` writes metres. Normals are real (vn); UVs are mapped into
the full texture. Earlier versions of this script read the wrong words as UVs: re-export anything made with them.

## Material table = how textures are mapped to models.
#### Reverse-engineered from the game's loader and verified on Gamel.art / GAME.ART (all 42 RSS files); see TEXTURE_MAPPING.md.

The table follows the header line, before any mesh data. 

### Record layout:
label\0  body[39]  [texture\0 rect[4 x u32]  (leaf surfaces only)]  nchild:u16   + nchild child records

body[6:9] is always e5 e5 e5 (used as the record signature); body[0:6] looks like colours.

rect = u, v, w, h as 1.15 fixed point (/32768): a sub-rectangle of the texture, v from the TOP.

A mesh block is tied to a top-level group by NAME; a face's u16 flag is the index of the group's

child surface (0 for a group that is itself a leaf). Face-vertex UVs are 16.16, local to the

surface rect, v pointing UP:

texel_x = (rect.u + u*rect.w) * tex_w      texel_y = (rect.v + (1-v)*rect.h) * tex_h