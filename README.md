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

- **One-click examples** — six built-in models (prism, cube, cylinder, sphere, torus, cone)
  with **editable dimensions** (the prism can drill an optional length-wise channel),
  each pre-loaded with showcase parameters.
- **Drag-and-drop any STL** — slices to a registered, fixed-canvas photostack.
- **Five grayscale modes**
  - **Uniform** — flat exposure for every cured pixel.
  - **Edge-feather gradient** — gray ramps from walls/holes into the core by distance.
  - **Cubic tessellation** — white cube-edge support columns (grey faces/core), solid-white
    caps, a per-layer white outer-wall rim, and an optional black-void core per cell.
  - **Triangular prisms** — vertical strut columns + flat triangular frames (a triangular
    grid extruded in Z; no sloped struts).
  - **Octet truss** — Buckminster-Fuller's space-filling **tetrahedra + octahedra** (the FCC
    strut lattice): sloped struts run diagonally between layers, so the cells are true 3D
    pyramids. Defined by its strut segments — a voxel is white when within the strut radius
    of one — so the printed photostack and the 3D cage are one geometry.
- **Structure→core gradient** — grade each tessellation cell from its white struts
  inward to a black core with a **draggable ramp editor** *or* typeable numeric
  stops (add/move/remove points; **linear** or **step**/piecewise) — a functionally-
  graded material. The gradient flows inward *per element*: cubic from the struts,
  triangular from each triangle's edges to its centroid, octet radially into **both**
  its octahedral and tetrahedral void pockets. Design it live on the 3D **Element**
  view (one unit cell).
- **Connect voids** — a toggle that finds **every** void in the print (black cores
  *and* the shells of a void→light→void grade) and links them into one connected,
  drainable perfusion network — a tissue-scaffold vasculature analogue. It isn't a
  free-floating gyroid: because a tessellation is periodic, the channels are planned
  on **one unit cell** and tiled, so they match the *actual* voids (cubic + octet).
  Triangular's row spacing is irrational (not integer-tileable), so its layer-constant
  voids are connected in 2D and extruded. **Route** is `geodesic` (shortest straight
  tubes) or `tpms` (organic curved tubes); **Drain** breaches the skin so the network
  reaches the surface. Enabled only when there *are* voids (a `core_px`, or a grade
  that ramps to black). Pure-gradient (non-tessellation) parts fall back to the legacy
  gyroid minimal surface.
- **Live web studio** — upload, scrub the layer stack (with zoom), orbit the model in 3D
  (Mesh / Photostack / Wireframe / 1:1 Voxels / Element), hover-tooltips on every parameter, export.
- **Reproducible** — every photostack ships a `manifest.json` (source + all parameters) and a
  parameter-encoded zip name; every run is fully described by one JSON config.

![3D model view](docs/screenshot-3d.png)

---

## Download for Windows (one-click)

**[⬇ Download LumenGray-Setup.exe](https://github.com/rsiegemit/LumenGray/releases/latest/download/LumenGray-Setup.exe)** — run the installer (no admin needed), then launch **LumenGray** from the Start Menu. It starts a local server and opens the studio in your browser automatically; no Python required.

> First launch may show a Windows SmartScreen warning (the installer isn't code-signed) — click **More info → Run anyway**. Prefer no installer? Grab the portable **`LumenGray-windows.zip`** from the [latest release](https://github.com/rsiegemit/LumenGray/releases/latest), unzip, and run `LumenGray.exe`. A macOS `.app` is on the same release.

## Install (from source)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"     # core + web UI; drop [web] for just the CLI/library
```

## Run it in the cloud (share with anyone — no install)

Host LumenGray once and everyone just opens a **URL** — any OS, no Python, no
download. Every push to GitHub auto-redeploys the latest code.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rsiegemit/LumenGray)

Click the button → sign in to Render → **Apply**. In ~2 minutes you get a public
URL (e.g. `https://lumengray.onrender.com`) running this repo, redeploying on
every push (`render.yaml`). The blueprint builds from the repo **`Dockerfile`**
(Docker runtime) for a deterministic build, so the same image also runs on
Fly.io / Hugging Face Spaces / Railway / Cloud Run. (Render's free tier sleeps
when idle and wakes on the next visit; the first hit after a nap takes a few
seconds, and it fits the 512 MB free tier.)

## The web studio (run locally)

```bash
lumengray-web               # opens http://127.0.0.1:8000 in your browser
# or: python -m lumengray.web
```

Upload an STL — or click an **Example** to load a built-in model with showcase parameters —
pick a grayscale mode, drag the sliders, and the **Layer stack** preview re-slices live
(scroll-zoom + drag-pan). Hit **Export stack (.zip)** for the full set of PNG masks plus a
`manifest.json`.

The **3D model** tab has five orbitable views:

- **Mesh** — the input STL.
- **Photostack** — the literal rendered layers stacked as thin slices.
- **Wireframe** — the print's 3D structure. For **tessellation** modes it's a **strut
  cage** (columns + square/triangular frame edges, or the octet's sloped tetrahedra
  struts) computed from the parameters and clipped per layer so it follows curved
  shapes; for other modes it's an exposure-**band** cage.
- **1:1 Voxels** — *true machine voxels*, one solid box per print pixel at its **exact
  0–255 exposure** (the full grayscale gradient, not quantized to bands) — a literal
  preview of what the printer lays down. The **Structure / Diffusion / Void** toggles
  *filter* which voxels are shown (with editable exposure thresholds), and a
  **layer-range slab** keeps the millions of voxels interactive (inspect just the
  structure, or just the lumen network, before printing).
- **Element** — exactly **one** tessellation unit cell as a crisp white **strut cage**
  with the graded grey→black infill shown as translucent voxels inside it — the live
  design surface for the structure→core gradient. The cage is the element's true
  geometry: a cube for cubic, a prism for triangular, and for octet the faithful
  **primitive** (1 octahedron + 2 tetrahedra), filled to every corner (struts included)
  so it reads as one solid repeating cell.

Two **Cutaway** sliders — **Vertical** (the cut travels up/down along Z) and
**Horizontal** (the cut travels side to side along X) — clip any view to see inside.

![Built-in examples](docs/screenshot-presets.png)
![3D wireframe view](docs/screenshot-wireframe.png)

## The CLI

```bash
# Uniform white masks (defaults: 1920×1080, 35µm XY voxels, 50µm voxel height)
lumengray model.stl -o ./out --preview

# Hollow-cube infill (drag-and-drop on any STL)
lumengray model.stl --cubic-tessellation -o ./out --grey-value 128

# Everything driven by a JSON config
lumengray model.stl -c config.tessellation.json -o ./out
```

Useful flags: `--voxel-height-um`, `--falloff-mm`, `--rotate-x/y/z`, `--prefix`,
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
  // voxel_width_um/voxel_length_um = XY pixel pitch (µm); voxel_height_um = Z layer (20/50/100)
  "printer": { "resolution": [1920, 1080], "voxel_width_um": 35, "voxel_length_um": 35, "voxel_height_um": 50 },
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

    "cubic_tessellation": {                      // OR the hollow-cube strut infill
      "cap_bottom_layers": 2, "cap_top_layers": 2,
      "cube_xy_px": 6, "cube_z_layers": 6, "shell_px": 1,
      "core_px": 0,                              // optional black-void cube per cell (0 = none)
      "boundary_px": 3, "grey_value": 128, "white_value": 255
    },

    "triangular_tessellation": {                 // OR triangular prisms (columns + flat frames)
      "cap_bottom_layers": 2, "cap_top_layers": 2,
      "tri_px": 10, "z_layers": 6, "shell_px": 1,
      "core_px": 0, "boundary_px": 3, "grey_value": 128, "white_value": 255
    },

    "octet_tessellation": {                      // OR the octet truss (Fuller tetrahedra+octahedra)
      "cap_bottom_layers": 2, "cap_top_layers": 2,
      "cell_xy_px": 14, "cell_z_layers": 10,     // FCC cube-cell edge (node spacing = half)
      "strut_px": 1,
      "core_px": 0,                              // octahedral black-void core per cell (0 = none)
      "boundary_px": 3, "grey_value": 128, "white_value": 255
    },

    "connect_voids": {                           // link every void into one drainable network
      "route": "geodesic",                       // "geodesic" (straight) | "tpms" (curved)
      "channel_px": 1,                           // carved void channel width (voxels)
      "drain": false,                            // true → breach the skin to drain to the surface
      "skin_px": 3,                              // solid wall kept at the boundary (ignored when drain)
      "cell_mm": 0.8                             // legacy TPMS-surface period (pure-gradient fallback only)
    },

    "grade": {                                   // structure->core exposure ramp (tessellation cells)
      "stops": [[0.0, 255], [1.0, 0]],           // (distance 0=struts..1=core, value) control points
      "interp": "linear"                         // "linear" (continuous) or "step" (piecewise)
    }
  }
}
```

(Wireframe is a 3D *visualization*, not a grayscale mode, so it has no config block.)

### Tessellation, in detail

A tessellation tiles the model interior with a strut lattice: white **support struts**
(columns at the grid nodes, braced by horizontal frames every `z`/`cube_z_layers` layers),
grey faces/core, solid-white caps top and bottom, and a white rim on the part's **outer
wall** (solid pixels within `boundary_px` of an edge, L∞ / chessboard — internal channels are
excluded). An optional **`core_px`** carves a black void in each cell's centre.

**Cubic** and **triangular prisms** share one base (`tessellation._assemble`); a *kind* only
supplies its XY grid — cubic uses a square grid (columns + rows), triangular uses three line
families at 60° (equilateral triangles). The **octet truss** (`octet.py`) is separate: an FCC
nearest-neighbour strut lattice with **sloped** struts between layers, defined by its strut
segments and voxelized per layer (a voxel is white within the strut radius of one), so the
print and the 3D cage are the same geometry; its optional core carves an **octahedral** void.
Everything is reasoned about in **voxels** — one voxel is an output pixel in XY and one
photostack layer in Z — so at the Lumen X3's 35 µm XY / 50 µm Z the cells are deliberately
*approximate*.

Two **overlays** compose on top of any of these:

- **`grade`** (`grade.py`) — a structure→core exposure ramp (white struts → designed greys →
  black core) from a draggable/typeable list of `(distance, value)` stops, `linear` or `step`.
  Each mode supplies its own per-element inward-depth field (`0` at the struts → `1` at the
  core) so the gradient flows cleanly inward: cubic by distance from the struts, triangular by
  distance from each triangle's lines to its centroid, and octet radially from **both** its void
  types — the octahedral holes (anti-nodes) and the tetrahedral pockets (quarter-cell sites).
- **`connect_voids`** (`void_connect.py`) — find every void and link them into one drainable
  network. Exploits tessellation periodicity: plan the channels on one unit cell (via the
  tiling-connectivity theorem — link each void component to a hub, then port to each face at
  the hub's projected transverse coord) and tile them (cubic/octet); triangular connects its
  layer-constant voids in 2D and extrudes. `route` = geodesic/tpms, `drain` breaches the skin.
  Pure-gradient parts fall back to the legacy gyroid (`gyroid.py`).

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
| `tessellation.py` | shared tessellation base + the cubic kind |
| `triangulation.py` | triangular-prism kind, reusing the shared base |
| `octet.py` | octet truss (Fuller tetrahedra+octahedra): strut generator, per-layer voxelizer + gradient depth |
| `void_connect.py` | algorithmic void-connector — per-cell unit-cell tiling (cubic/octet) + 2D-extrude (triangular), geodesic/tpms routes |
| `gyroid.py` | legacy gyroid (TPMS) surface — fallback connector for pure-gradient parts |
| `grade.py` | structure→core exposure gradient — applies the ramp to each mode's inward-depth field |
| `geometry.py` | mm ↔ output-pixel coordinate mapping |
| `config.py` | immutable, validated config + `config_to_dict` serializer |
| `pipeline.py` | end-to-end run, shared single-layer renderer, manifest + naming |
| `web/` | FastAPI backend + zero-build ES-module SPA (core/api/config/viewer3d/ramp/app) |

### Metadata & naming

Every photostack includes a **`manifest.json`** recording what made it: the **source**
(uploaded STL filename, or preset name + the dimensions used) and the **full grayscale mode +
parameters**, plus printer/model settings, layer count, and a timestamp. The exported zip is
named from those parameters, e.g. `Rectangular-prism_50um_cubic-xy6-z6-s1-b3_core2.zip`.

## Development

```bash
pip install -e ".[web]"
python smoke_test.py    # end-to-end: regions, gradient, rotation, cubic/triangular/octet tessellation,
                        # octahedral cores, void-connector, structure→core grade, manifest
```

## License

MIT
