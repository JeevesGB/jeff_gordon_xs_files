# fRssExport V1 (.RSS) file format

Derived from the game's own loader (`gfx3Dload.c`: FUN_00447ff0, 00447930, 00447270, 00447dd0 in the Ghidra project)
and verified by parsing **all 42 RSS files of GAME.ART and Gamel.art exactly to the last byte** (`rss_extract.walk_objects`).
All values little-endian. u32 words that are positions/UVs are fixed point.

```
header line        "fRssExport Version (V1) - <date>\n"
u16 version        5 for cars/wheels, 1 for tracks (fields marked [v>=N] depend on it)
3 bytes            0b 0b 0b (flags, unused here)
u16 ngroups        material table (see TEXTURE_MAPPING.md)
u16 nobjects
object * nobjects
```

## Object
```
u8   type          0 = mesh, 1 = driving line ("dl", "dl1", ...)
str  name          NUL-terminated
str  parent        NUL-terminated, may be empty (the game links child -> parent; the transform below is discarded so it moves nothing)
```
**type 0**
```
[v>3] u32 flags
6 x i32            transform (read, then zeroed by the game)
[v>4] u16 n, n x 24 bytes   extra entries (purpose unknown, n is 0 in the files seen)
[v>=4] u16 nsub  (else 1)
submesh * nsub
```
**type 1** (driving line)
```
6 x i32 transform (discarded)
u16 nsets ; per set: u16 n, n x (i32 x, i32 y, i32 z)
```
SSKIDPAD's `dl` has one set of 29 points; tracks have 0-3 such objects.

## Submesh
```
[v>=4] u32 flags, u32 radius      (radius: game squares 2*value; bounding radius)
[v>=3] u16 poses (else 1)
u16 nverts
poses * nverts * (i32 a, i32 b, i32 c)   positions
str  material group name          (matches a top-level label in the material table)
u16 nfaces
u8  has_colour
face * nfaces
```
**Position scale:** value * 12 / 32768 = game units (inches: wheel diameter 26.6, track ~900 m). File axes are Z-up;
the game's runtime frame is (x, y, z) = (-a, c, -b). `rss_extract.py` writes file-frame positions in inches (`--metres` for metres).

## Face
```
3 x u32                           ignored by the game
[v>=2] u16 nv (else 3)
vertex * nv:  u16 index
              3 x i32 normal      value/32768 is a unit vector; file-frame normal = (-w2, -w0, w1)
              2 x i32 u, v        16.16, local to the surface rectangle; the game uses v' = 1 - v
              [has_colour] 3 bytes r, g, b
u16 surface                       material surface = group.children[surface % nchildren]
```
Stored winding is counter-clockwise = outward for car bodies in the file frame (99-100% agreement with the normals).
Track and wheel faces disagree with their normals about half the time (mirrored parts / two-sided surfaces?): unresolved.

## Not known
* purpose of `poses`, the `[v>4]` extra entries, `flags` bits, the 39-byte surface body (beyond colour bytes),
* the vertex-slot table at 0x004653c8 (probably a winding reorder to suit the game's mirrored frame),
* per-vertex colours (`has_colour`, 36 submeshes in SFUTURE) are parsed but not exported yet.
