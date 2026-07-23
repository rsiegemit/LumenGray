# LumenGray

**Turn an STL into a grayscale photostack for the [Lumen X3](https://en.wikipedia.org/wiki/Volumetric_display).**

LumenGray slices a 3D model into an ordered stack of 8-bit grayscale PNG masks — one per
print layer, where each pixel's gray value sets the *local exposure*. It replaces the manual
"Chitubox → slice/export → ImageJ paint" workflow with a scriptable library, a CLI, and a
live browser studio.

![LumenGray layer viewer](docs/screenshot-layers.png)

---

## Download

The desktop apps bundle everything (no Python needed). Launch one and it starts a local
server and opens the studio in your browser.

| Platform | Get it | Install |
|----------|--------|---------|
| **Windows** | [**⬇ LumenGray-Setup.exe**](https://github.com/rsiegemit/LumenGray/releases/latest/download/LumenGray-Setup.exe) | Run the installer (no admin) → launch **LumenGray** from the Start Menu. |
| **macOS** | [**⬇ LumenGray-macos.dmg**](https://github.com/rsiegemit/LumenGray/releases/latest/download/LumenGray-macos.dmg) | Open it → drag **LumenGray** onto **Applications**. |

> The apps are unsigned, so the **first** launch needs a one-time confirm — Windows:
> SmartScreen → *More info → Run anyway*; macOS: *right-click → Open → Open*. After that,
> open them normally. There's a **Check for updates** button in the app header, and portable
> `.zip` builds are on the [latest release](https://github.com/rsiegemit/LumenGray/releases/latest).

**Other ways to run:**

- **Cloud** — [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rsiegemit/LumenGray) → a public URL in ~2 min, no install, redeploys on every push (`render.yaml` builds from the repo `Dockerfile`, so it also runs on Fly.io / Railway / Cloud Run / HF Spaces).
- **From source** — `pip install -e ".[web]"`, then `lumengray-web`.

---

## Features

**Five grayscale modes** — pick one per stack:

- **Uniform** — one exposure for every cured pixel.
- **Gradient** — a positional ramp designed on a graph: **radial** (centre → edge) or
  **linear** along **X / Y / Z**, mapped through `(position, value)` stops with **Smooth** or
  **Step** interpolation, plus an optional solid **rim** wall around the graded interior and,
  on **Step**, a white **crosslink seam** welding adjacent bands. (The structure→core grade
  gets the same Step seam.)
- **Cubic / Triangular / Octet** — strut-lattice infills: white support struts, grey
  faces/core, solid-white caps, a white outer-wall rim, and an optional black void core per
  cell. Cubic uses a square grid, triangular a 60° grid (columns + flat frames), and **octet**
  the FCC tetrahedra + octahedra lattice with *sloped* 3D struts.

**Two overlays** compose on top of any tessellation:

- **Structure→core gradient** — grade each cell from its white struts inward to a black
  core via a draggable/typeable ramp (Smooth or Step). Design it live on the 3D **Element**
  view.
- **Connect voids** — link every void into one connected, drainable **lumen network**.
  **Void ≤** sets what counts as void (raise it to catch a gradient's *near*-black cores, not
  just exact black); channels are straight (`geodesic`) or organic (`tpms`); **Drain** breaches
  the outer skin to reach the surface.

**Live 3D studio** — orbit the model in five views: **Mesh**, **Photostack**, **Wireframe**
(strut cage or exposure-band cage), **1:1 Voxels** (true per-voxel 0–255 exposure, filtered by
Structure / Diffusion / Void), and **Element** (one unit cell). Two **Cutaway** sliders —
**Vertical** (up/down, Z) and **Horizontal** (side to side, X) — slice into any view.

**Batch** — print **N identical copies** on one photostack, auto-arranged on a centred grid
with a parametric mm gap so neighbours don't fuse. Each copy renders identically (every part
gets its own gradient normalization).

**Calibration chip** — a header button opens a dedicated page that generates a **LumenX
calibration test print** (no STL needed). The focus is a resizable **~1 cm gel chip** for the
small plate — genuinely 3D, printable in hydrogel: **pyramids** (min printable pillar),
**wells** (min open well), **channels** (min open width), and a grayscale **checker** — with
adjustable chip size, height (Z), pyramid grid, channel count, and checker range. Every voxel is
35 × 35 µm XY × the layer-height µm Z. Views: a labeled **reference** map (labels live only here /
in the exported `reference.png`, never in the print), the **gel-print** layers, and a **3D** view —
all with scroll-to-zoom, pan, and a draggable **scale bar**. Print it, measure it, then the
**step-by-step wizard** records your **printability limits**; on any studio export, features below
a limit are **flagged** and — only if you tick **"Allow"** — grown to the printable minimum. The
**X/Y voxel pitch** is editable in the Printer card to correct dimensional scale. (A full-build
dimensional/grayscale chip + solver also exist in the backend.)

**Reproducible** — every export ships a `manifest.json` (source model + every parameter) and a
parameter-encoded filename; a whole run is described by one JSON config. Drop that
`manifest.json` back onto the studio to restore the whole session.

![3D model view](docs/screenshot-3d.png)

---

## Using it

### Web studio

```bash
lumengray-web        # opens http://127.0.0.1:8000
# or: python -m lumengray.web
```

Upload an STL — or click an **Example** to load a built-in model (prism, cube, cylinder,
sphere, torus, cone) with showcase parameters — pick a mode, drag the sliders, and the layer
preview re-slices live (scroll-zoom, drag-pan). **Export stack (.zip)** writes every PNG mask
plus the manifest.

![Built-in examples](docs/screenshot-presets.png)

### CLI

```bash
lumengray model.stl -o ./out --preview                        # uniform + a thumbnail grid
lumengray model.stl --cubic-tessellation --grey-value 128 -o ./out
lumengray model.stl -c config.tessellation.json -o ./out       # full JSON config
```

Flags: `--voxel-height-um`, `--rotate-x/y/z`, `--prefix`, `--preview`.

### Library

```python
from lumengray import load_config, run
summary = run("model.stl", "./out", load_config("config.tessellation.json"))
print(summary["layers"], "masks written")
```

---

## Config reference

One JSON object fully describes a run. Choose **one** grayscale mode; the overlays and regions
are optional.

```jsonc
{
  // voxel_width_um/voxel_length_um = XY pixel pitch (µm); voxel_height_um = Z layer (20/50/100)
  "printer": { "resolution": [1920, 1080], "voxel_width_um": 35, "voxel_length_um": 35, "voxel_height_um": 50 },
  "model":   { "center_xy": true, "rotation_deg": [0, 0, 0],
               "array_count": 1, "array_spacing_mm": 2 },   // batch N identical copies on one plate, mm apart

  "grayscale": {
    // --- pick ONE base mode ---
    "default_solid_value": 255,                  // uniform fill for cured pixels

    "gradient": {                                // OR a designed radial/linear ramp
      "mode": "radial",                          // "radial" (centre→edge) | "linear"
      "axis": "x",                               // linear direction: "x" | "y" | "z"
      "stops": [[0.0, 255], [1.0, 0]],           // ramp graph: (position 0..1, value 0..255)
      "interp": "linear",                        // "linear" (Smooth) | "step"
      "rim_px": 0,                               // optional solid outer wall this many px thick (0 = none)
      "rim_value": 255,                          // rim exposure (255 = white / full structure)
      "band_px": 0                               // step only: white crosslink wall this many voxels thick at each step seam
    },

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

    // --- optional: painted regions (rect / circle / polygon), later ones win ---
    "regions": [
      { "name": "dot", "value": 128, "units": "mm",
        "shape": { "type": "circle", "cx": -12, "cy": 6, "r": 2 },
        "layers": [1, 20], "clip_to_solid": true }
    ],

    // --- optional overlays (tessellation modes) ---
    "grade": {                                   // structure→core exposure ramp per cell
      "stops": [[0.0, 255], [1.0, 0]],           // (distance 0=struts..1=core, value)
      "interp": "linear",                        // "linear" (Smooth) | "step"
      "band_px": 0                               // step only: white crosslink wall this many voxels thick at each step seam
    },

    "connect_voids": {                           // link every void into one drainable network
      "route": "geodesic",                       // "geodesic" (straight) | "tpms" (curved)
      "void_max": 0,                             // exposure ≤ this counts as void (0 = only black)
      "channel_px": 1,                           // carved channel width (voxels)
      "drain": false,                            // true → breach the skin to drain to the surface
      "skin_px": 3,                              // solid wall kept at the boundary (ignored when drain)
      "cell_mm": 0.8                             // legacy TPMS period (pure-gradient fallback only)
    }
  }
}
```

Everything is reasoned about in **voxels** — one voxel is one output pixel in XY and one
photostack layer in Z — so at the Lumen X3's 35 µm XY / 50 µm Z the lattices are deliberately
*approximate*. Each export's zip is named from its parameters, e.g.
`Rectangular-prism_50um_cubic-xy6-z6-s1-b3_core2.zip`.

---

## How it works

```
STL ─► orient ─► slice (trimesh) ─► per-layer binary mask ─► grayscale mode ─► 8-bit PNG stack + manifest.json
```

| Module | Role |
|--------|------|
| `slicer.py` | STL → registered binary layer masks (fixed world-space canvas) |
| `grayscale.py` | uniform / radial·linear gradient base fill + region overlay |
| `tessellation.py` | shared tessellation base + the cubic kind |
| `triangulation.py` | triangular-prism kind, reusing the shared base |
| `octet.py` | octet truss: strut generator + per-layer voxelizer + inward-depth field |
| `grade.py` | structure→core exposure ramp applied to each mode's depth field |
| `void_connect.py` | void-connector — unit-cell tiling (cubic/octet) + 2D-extrude (triangular), geodesic/tpms |
| `gyroid.py` | legacy gyroid (TPMS) surface — fallback connector for pure-gradient parts |
| `geometry.py` | mm ↔ output-pixel coordinate mapping |
| `config.py` | immutable, validated config + JSON (de)serialization |
| `pipeline.py` | end-to-end run, shared single-layer renderer, manifest + naming |
| `web/` | FastAPI backend + zero-build ES-module SPA |

The **Connect voids** step is exact rather than a free-floating gyroid: because a tessellation
is periodic, its channels are planned on **one unit cell** and tiled, so they match the real
voids (cubic + octet). Triangular's row spacing is irrational, so its layer-constant voids are
connected in 2D and extruded instead.

---

## Development

```bash
pip install -e ".[web]"
python smoke_test.py    # end-to-end: regions, gradient, rotation, all tessellations,
                        # cores, void-connector, structure→core grade, manifest
```

## License

MIT
