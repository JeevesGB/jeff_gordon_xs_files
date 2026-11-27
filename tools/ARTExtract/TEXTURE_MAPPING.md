# How textures are mapped to models in fRssExport V1 (.RSS) files

Reverse-engineered from `Gamel.art` (21 RSS files). Nothing here comes from documentation.
`rssmat.py` is the reference implementation; `rss_preview.py` renders a model with it.

## Summary

A model's texturing is defined by a **material table** that sits right after the header line,
before any mesh data. Meshes do not store texture names. Each mesh is tied to the table by
**name**, and each face picks one **surface** in that table by a small integer **flag**.
A surface names a texture and a **rectangle** inside it, and the face's own UVs are
**local to that rectangle**. In other words, each texture is an atlas.

```
mesh block  --name-->  table group  --face flag-->  surface  --texture name--> NAME.png  (from the .ART)
                                                      \--rect--> sub-rectangle of that PNG
face vertex (u,v) local 0..1 across the rect
```

## 1. The material table

Records are NUL-terminated label + a 39-byte body. A record with children is followed by exactly
that many child records.

| part | size | meaning |
|---|---|---|
| label | NUL-terminated | e.g. `Alien_0` (group) or `Alien Front_0` (surface) |
| body | 39 bytes | bytes 0-5 colour(s) (`ff ff ff` white, `ad ad ad`, `ff 00 00` red on `Pole`); bytes 6-8 always `e5 e5 e5`; 9-14 `00 20 00 00 66 06` or zeros; rest **not decoded** |
| texture | NUL-terminated | present on leaf surfaces only; equals an entry name in the `.ART` (`Alien`, `tire1`, ...) |
| rect | 4 x u32 | `u, v, w, h` as **1.15 fixed point (value / 32768)**, fractions of the texture, v measured from the **top** |
| nchild | u16 | number of child records that follow |

Evidence for the 1.15 scale: across all 94 (file, texture) groups the largest `u+w` / `v+h` is
exactly 0.500; the full-texture shadow rect is `0x8000` = 1.0.

## 2. Linking a face to a surface

* A mesh block's **name** equals a top-level group's label (including the original typos, `Aien Airbrake`).
  The same name can occur in several mesh blocks (`Alien_0` is three blocks: body, underside, wing).
* A face's u16 **flag** selects the surface as `children[flag % nchildren]` (the game's own rule; from the decompiled loader)
  (`Alien_0`: 0 Front, 1 Top, 2 Back, 3 Side, 4 Bottom, 5 Wing). A group that is itself a leaf (`car shadow`) is its own surface for any flag.
* LOD groups (`Alien_1`, `Alien_2`) are separate groups; `Alien_2` points at a different, smaller texture (`Alien1_2`) with a full-texture rect.

## 3. UV transform

Face-vertex UVs are 16.16 fixed point, 0..1 across the surface, **v pointing up**:

```
texel_x = (rect.u + u * rect.w) * texture_width
texel_y = (rect.v + (1 - v) * rect.h) * texture_height      # origin top-left of the PNG
```

U is not mirrored. V is inverted relative to the PNG rows (see checks).

## 3b. Per-vertex words in a face record (correction)

Each face vertex is `u16 index` + five u32 words. Words are 16.16 fixed point and **signed**:

| words | meaning |
|---|---|
| 0, 1, 2 | **vertex normal** (confirmed by the game's loader: stored as value/32768; file-frame normal = (-w2, -w0, w1)). Raw words are a vector of length **exactly 0.5** (all 5,544 sampled). Not used for texturing. On the car bodies the face winding as stored agrees with these normals for 99-100% of faces (CCW = outward in the file frame). |
| **3, 4** | **the UV** (local to the surface rect, v up) |

Earlier versions of `rss_extract.py` read words 0 and 1 as UVs (and as unsigned). That was wrong: the old `*.obj` `vt` lines and the
`uv_fixed16` field in `*.mesh_data.json` were normal components. They are fixed in the updated script.

## 4. How it was checked

* **Table parser:** parses all 21 files: 225 groups, 747 surfaces.
* **Name + flag link:** all 59 mesh blocks that have a recovered vertex array link to a group, with every face flag resolving.
* **Texture names:** all 221 distinct texture names in the tables have a decoded PNG in `textures_png/`.
* **GAME.ART:** all 21 tables parse (273 groups); all 64 meshes with a vertex array link by name and flag; all 256 distinct texture names have a decoded PNG.
* **Visual:** six cars render as coherent textured cars (`texture_mapping_check.png`): wheel arches at the
  bottom edge, cockpit/vents/tail-lights in the right places, livery stripes continuous across surfaces.
  Wrong V (not flipped) puts wheel arches at the roof; wrong scale (16.16 rect) gives garbage.
* **Text:** the Pepsi lettering on the airbrake panels reads left-to-right with U unflipped, reversed with U flipped.
  It appears upside-down from above, which is consistent with a one-sided panel seen from its back face.
* **Export round trip:** textured OBJ/MTL files written by the updated `rss_extract.py` were re-read by an independent loader and
  rendered: 11 of 11 per-mesh files are pixel-identical to rendering straight from the RSS; the combined `all_meshes` files hold exactly the same triangles (7/7).
* **Wheels:** looking along the axle the rim and tyre lettering land correctly; edge-on you get the black tread strip
  (`Tread` rect is a small black corner of `tire1`).

## 5. Not verified / open

* **Tracks (`S*.RSS`):** now parsed exactly (see RSS_FORMAT.md). The same mapping gives coherent textures (SPLANET: starry sky dome with
  sunset horizon, planet track surface, tower). Not yet checked surface by surface.
* **Mesh finder:** replaced by an exact walker; the false positives were the flag/modulo cases and a few mis-detected blocks.
* **Poses:** a submesh stores `poses x nverts` positions (cars: 2, tracks: 1). Pose 0 is used. Their purpose is unknown.
* **Body bytes:** colours are inferred (a red `Pole` surface has no texture and body `ff0000 ff0000`); the other body bytes are undecoded.
  Eight surfaces have no texture: `Not Used`, `T Empty`, `NU...` (probably "not used") and `Pole` (flat colour).
* **Transparency:** palette entry 0 (blue 0,0,255) is probably a colour key; not tested here.
* Developed on `Gamel.art`. `GAME.ART` was checked afterwards with the same parser: see section 4.
