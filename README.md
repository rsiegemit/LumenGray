# LumenGray

**STL → grayscale photostack studio for the [Lumen X3](https://en.wikipedia.org/wiki/Volumetric_display).**

LumenGray turns a 3D model into an ordered stack of 8-bit grayscale PNG masks — one per
print layer — where the gray value of every pixel sets the *local exposure*. It replaces
the manual "Chitubox config → slice/export → ImageJ paint" workflow with a scriptable
library, a CLI, and a browser studio where you can tweak parameters and watch the layer
stack update live.

![LumenGray layer viewer](docs/screenshot-layers.png)

---

## Highlights

- **Drag-and-drop any STL** — slices to a registered, fixed-canvas photostack.
- **Three grayscale modes**
  - **Uniform** — flat exposure for every cured pixel.
  - **Edge-feather gradient** — gray ramps from walls/holes into the core by distance.
  - **Cubic tessellation** — a 3D infill of hollow white cubes (white shell, grey core)
    with solid-white caps and a per-layer white boundary rim.
- **Live web studio** — upload, scrub the layer stack, orbit the model in 3D, export.
- **Reproducible** — every run is fully described by one JSON config you can save and share.

![3D model view](docs/screenshot-3d.png)

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"     # core + web UI; drop [web] for just the CLI/library
```

## The web studio

```bash
lumengray-web               # opens http://127.0.0.1:8000 in your browser
# or: python -m lumengray.web
```

Upload an STL, pick a grayscale mode, drag the sliders, and the **Layer stack** preview
re-slices live. Switch to **3D model** to orbit the mesh. Hit **Export stack (.zip)** for
the full set of PNG masks plus a `manifest.json`.

## The CLI

```bash
# Uniform white masks (defaults: 1920×1080 @ 35µm XY, 50µm Z)
lumengray model.stl -o ./out --preview

# Hollow-cube infill (drag-and-drop on any STL)
lumengray model.stl --cubic-tessellation -o ./out --grey-value 128

# Everything driven by a JSON config
lumengray model.stl -c config.tessellation.json -o ./out
```

Useful flags: `--layer-height-um`, `--falloff-mm`, `--rotate-x/y/z`, `--prefix`,
`--preview` (writes a contact-sheet thumbnail grid).

## As a library

```python
from lumengray import load_config, run
summary = run("model.stl", "./out", load_config("config.tessellation.json"))
print(summary["layers"], "masks written")
```

---

## Config schema

```jsonc
{
  "printer": { "resolution": [1920, 1080], "pixel_size_um": 35, "layer_height_um": 50 },
  "model":   { "center_xy": true, "rotation_deg": [0, 0, 0] },
  "grayscale": {
    "default_solid_value": 255,                 // uniform fill for cured pixels

    "gradient": {                               // OR an edge-feather gradient
      "type": "edge_feather", "min": 40, "max": 255, "falloff_mm": 0.35
    },

    "regions": [                                // OR painted shapes (rect/circle/polygon)
      { "name": "dot", "value": 128, "units": "mm",
        "shape": { "type": "circle", "cx": -12, "cy": 6, "r": 2 },
        "layers": [1, 20], "clip_to_solid": true }
    ],

    "cubic_tessellation": {                      // OR the hollow-cube infill (overrides the above)
      "cap_bottom_layers": 2, "cap_top_layers": 2,
      "cube_xy_px": 6, "cube_z_layers": 6, "shell_px": 1,
      "boundary_um": 100, "grey_value": 128, "white_value": 255
    }
  }
}
```

### Cubic tessellation, in detail

The model interior is filled with a lattice of **hollow cubes**: a 1-voxel white shell
around a grey core. The stack is capped with solid-white layers top and bottom, and every
interior layer gets a pure-white boundary rim (within `boundary_um`, measured in the L∞ /
chessboard metric) so walls stay fully cured.

Everything is reasoned about in **voxels** — one voxel is an output pixel in XY and one
photostack layer in Z. With the Lumen X3's 35µm XY pixels and 50µm layers the voxels (and
therefore the cubes) are deliberately *approximate*: a default 6-voxel cube is
210 × 210 × 300 µm. Pixel/voxel counts are the source of truth; only `boundary_um` is
specified physically. The lattice is anchored to the canvas in XY and to the first interior
layer in Z, so cubes stack into true hollow boxes across the whole stack.

---

## How it works

```
STL ─► orient ─► slice (trimesh) ─► per-layer binary mask
                                       │
              grayscale mode ──────────┤
                                       ▼
                         8-bit PNG photostack  +  manifest.json
```

| Module | Role |
|--------|------|
| `slicer.py` | STL → registered binary layer masks (fixed world-space canvas) |
| `grayscale.py` | uniform / gradient base fill + region overlay |
| `tessellation.py` | hollow-cube 3D infill mode |
| `geometry.py` | mm ↔ output-pixel coordinate mapping |
| `config.py` | immutable, validated config (frozen dataclasses) |
| `pipeline.py` | end-to-end run + the shared single-layer renderer |
| `web/` | FastAPI backend + zero-build single-page UI |

## Development

```bash
pip install -e ".[web]"
python smoke_test.py        # end-to-end: regions, gradient, rotation, cubic tessellation
```

## License

MIT
