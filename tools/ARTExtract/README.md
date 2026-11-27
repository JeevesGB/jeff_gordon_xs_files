# ARTExtract 

Forensic extractor for fRssExport (V1) .RSS files.

The format is only partially understood. This tool therefore never treats an
unrecognised byte range as disposable: it preserves every source file verbatim,
records byte offsets, extracts text in several encodings, identifies common
embedded-file signatures, and optionally carves unparsed ranges. The OBJ parser
is heuristic and is reported separately from the lossless extraction.

Input may also be a game .ART archive (e.g. GAME.ART, Gamel.art). The RSS files
are unpacked from it verbatim, and its Q/q texture entries are decoded to PNG
(textures_png/, art_texture_manifest.json) and matched by name to each RSS file's
texture identifiers. The ART/texture layouts are reverse-engineered; see the
comment block above is_art().

Each RSS file's material table (how textures map onto models) is also parsed. When it
parses, the texture names come from it, material_table is written into the report, and
for every mesh with a recovered vertex array a textured OBJ (*.textured.obj, with UVs
already transformed into the full texture) is written next to <name>.mtl; the MTL points
at textures/<name>.png (copied from the ART's decoded PNGs). <name>.all_meshes.setN.textured.obj
holds every linked mesh in one file. The mapping rules are in the comment block above
parse_material_table(); they were verified visually on the car/wheel models only.

## Usage 
```
python rss_extract.py GAME.ART GAME.ART_out
python rss_extract.py Gamel.art Gamel.art_out
```

---

## .ART container + Q/q texture decoding.

### Container: 
 32-byte header slot ("Art\0", u32 @0x18 = entry count + 1,
   u32 @0x1C = file size), then (count-1) 32-byte directory entries:
   23-byte NUL-padded name, 1 type byte, u32 offset, u32 size.
   Type 0x44 ('D') entries are the .RSS files and JGRACING.INI; type 0x58 ('X')
   entries are textures.
### Texture: 
byte0 'Q' (0x51) = GIF-style LZW pixels, 'q' (0x71) = raw pixels;
u16 x, u16 y (meaning unverified), u16 width, u16 height; then w*h 8-bit
palette indices; the last 768 bytes are a 256-entry RGB palette.

## Material table = how textures are mapped to models.
#### Reverse-engineered from Gamel.art / GAME.ART (all 42 RSS files parse); see TEXTURE_MAPPING.md.

The table follows the header line, before any mesh data. 

### Record layout:
label\0  body[39]  [texture\0 rect[4 x u32]  (leaf surfaces only)]  nchild:u16   + nchild child records

body[6:9] is always e5 e5 e5 (used as the record signature); body[0:6] looks like colours.

rect = u, v, w, h as 1.15 fixed point (/32768): a sub-rectangle of the texture, v from the TOP.

A mesh block is tied to a top-level group by NAME; a face's u16 flag is the index of the group's

child surface (0 for a group that is itself a leaf). Face-vertex UVs are 16.16, local to the

surface rect, v pointing UP:

texel_x = (rect.u + u*rect.w) * tex_w      texel_y = (rect.v + (1-v)*rect.h) * tex_h