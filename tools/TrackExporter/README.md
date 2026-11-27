# TrackExporter

`run.bat` (run it from this folder) does two things:

1. `track_extract.py` exports the **track models** (the `S*.RSS` files in GAME.ART/Gamel.art) as textured OBJ + MTL into `track_models\<TRACK>\`
   (model, used textures, driving lines, summary). Options: `--split` (one OBJ per game object), `--yup`, `--metres`, `--all` (cars too).
2. `track_data_extract.py` decodes the per-track data files in `original\tracks` (`.trs` sounds, `.trc`, `.trl`, `.trk` driving-line parameters,
   `.trt` header only) to CSV/JSON in `track_data\`. Container layouts are exact; field meanings are guesses (see the docstring).

Needs `..\ARTExtract\rss_extract.py` (the exact-walker version) and `rssmat.py`, or copies of them in this folder.
