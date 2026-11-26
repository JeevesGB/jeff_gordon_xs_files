# fRssExport V1 texture research log

## Run result
- RSS files examined: 21
- Surface/texture-reference occurrences: 848; unique identifiers across archive: 266
- Reference records with plausible normalized 16.16 rectangle fields: 832/848
- Records with two zero padding bytes after the 16-byte field: 847/848
- Fully decoded image payloads: 0
- Valid zlib streams: 0

## Verified observations
- Material/surface labels are followed by short texture identifiers in the leading metadata tables.
- Immediately after most identifier NUL terminators is a 16-byte sequence that parses as four little-endian uint32 values; the next two bytes are `00 00` in nearly every detected record.
- 832 records have all four values within normalized bounds and satisfy `u + width <= 1.001`, `v + height <= 1.001`, with positive width and height.
- Example: ALIEN.RSS `Alien Front_0 -> Alien` gives approximately `(u=0, v=0, width=0.2475, height=0.0804)`. `Alien Top_0 -> Alien` gives `(0, 0.2412, 0.5, 0.1529)`.
- Example: SPPSI2K.RSS `Pepsi Red -> T6redblu` gives `(0, 0, 0.2499, 0.5)` and `Pepsi Blue -> T6redblu` gives `(0.2578, 0, 0.2422, 0.5)`, consistent with two atlas regions in one texture.
- No PNG/JPEG/BMP/GIF/PCX or decoder-validated TGA images were recovered; no valid zlib streams were found.

## Current hypothesis (not yet game-side confirmed)
- The four 16.16 values are `(u_origin, v_origin, u_extent, v_extent)` describing a sub-rectangle in an externally named texture atlas. The pattern is strongly supported by 832 plausible rectangles, but the exact field semantics and coordinate origin convention remain to be verified.
- The `.RSS` files appear to carry texture names and atlas mapping metadata, not the bitmap pixels themselves. The supplied archive contains no validated pixel payload.

## Unresolved
- Actual bitmap source files and their pixel format/dimensions/palette/compression/mipmaps are not present or not yet identified.
- Exact face-to-material assignment and the transform between face UVs and these atlas rectangles remain undecoded. Existing OBJ face parsing is heuristic and must not be treated as verified material mapping.
- Sixteen reference candidates have implausible rectangle words and are likely false positives from geometry strings; these remain in the raw catalog for audit rather than being silently discarded.

## Preservation
- Each RSS is copied byte-for-byte as `*.original`; no unknown source ranges are modified.
