"""Built-in example models, each parametric (editable dimensions) and paired
with its own grayscale parameters.

Every preset bundles a procedurally generated mesh (no STL files to ship) with a
full config in the public schema, so clicking one in the UI loads the geometry
*and* dials in a showcase of one grayscale mode. ``params`` lists the editable
size knobs (all in mm) the UI exposes.
"""

from __future__ import annotations

import numpy as np
import trimesh

_PRINTER = {"resolution": [1920, 1080], "pixel_size_um": 35, "layer_height_um": 50}
_MODEL = {"center_xy": True, "rotation_deg": [0, 0, 0]}


def _config(grayscale: dict) -> dict:
    return {"printer": dict(_PRINTER), "model": dict(_MODEL), "grayscale": grayscale}


def _cubic(**overrides) -> dict:
    base = {
        "cap_bottom_layers": 2,
        "cap_top_layers": 2,
        "cube_xy_px": 6,
        "cube_z_layers": 6,
        "shell_px": 1,
        "boundary_px": 3,
        "grey_value": 128,
        "white_value": 255,
    }
    base.update(overrides)
    return _config({"cubic_tessellation": base})


def _gradient(gmin: int, gmax: int, falloff_mm: float) -> dict:
    return _config({"gradient": {"type": "edge_feather", "min": gmin, "max": gmax, "falloff_mm": falloff_mm}})


def _uniform(value: int = 255) -> dict:
    return _config({"default_solid_value": value})


def _p(key: str, label: str, default: float, minimum: float = 0.1) -> dict:
    return {"key": key, "label": label, "default": default, "min": minimum}


def _prism(p: dict) -> trimesh.Trimesh:
    """A rectangular block, optionally drilled by a circular channel along its
    length (X) — straight through the centre of the width×height (e.g. 4×7) face."""
    box = trimesh.creation.box(extents=[p["length"], p["width"], p["height"]])
    d = p.get("channel", 0.0)
    if d and d > 0:
        bore = trimesh.creation.cylinder(radius=d / 2.0, height=p["length"] * 1.2)
        bore.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))  # Z→X
        try:
            return box.difference(bore)
        except Exception:  # noqa: BLE001 - no boolean backend → ship the solid block
            return box
    return box


# (id, name, description, params [editable mm dims], mesh builder(params), config)
PRESETS = [
    {
        "id": "prism",
        "name": "Rectangular prism",
        "description": "the canonical support-column demo (with an optional length-wise channel)",
        "params": [
            _p("length", "Length (mm)", 10.0),
            _p("width", "Width (mm)", 7.0),
            _p("height", "Height (mm)", 4.0),
            _p("channel", "Channel Ø (mm)", 1.0, minimum=0.0),
        ],
        "build": _prism,
        "config": _cubic(),
    },
    {
        "id": "cube",
        "name": "Cube",
        "description": "larger 8-voxel cubes",
        "params": [_p("edge", "Edge (mm)", 8.0)],
        "build": lambda p: trimesh.creation.box(extents=[p["edge"], p["edge"], p["edge"]]),
        "config": _cubic(cube_xy_px=8, cube_z_layers=8, grey_value=100, boundary_px=4),
    },
    {
        "id": "cylinder",
        "name": "Cylinder",
        "description": "edge-feather gradient on a round wall",
        "params": [_p("diameter", "Diameter (mm)", 10.0), _p("height", "Height (mm)", 6.0)],
        "build": lambda p: trimesh.creation.cylinder(radius=p["diameter"] / 2.0, height=p["height"]),
        "config": _gradient(40, 255, 1.0),
    },
    {
        "id": "sphere",
        "name": "Sphere",
        "description": "soft edge-feather gradient",
        "params": [_p("diameter", "Diameter (mm)", 10.0)],
        "build": lambda p: trimesh.creation.icosphere(subdivisions=3, radius=p["diameter"] / 2.0),
        "config": _gradient(20, 255, 1.5),
    },
    {
        "id": "torus",
        "name": "Torus",
        "description": "support columns in a loop",
        "params": [_p("ring_diameter", "Ring Ø (mm)", 12.0), _p("tube_diameter", "Tube Ø (mm)", 4.0)],
        "build": lambda p: trimesh.creation.torus(major_radius=p["ring_diameter"] / 2.0, minor_radius=p["tube_diameter"] / 2.0),
        "config": _cubic(cap_bottom_layers=1, cap_top_layers=1, grey_value=110),
    },
    {
        "id": "cone",
        "name": "Cone",
        "description": "uniform full exposure",
        "params": [_p("diameter", "Diameter (mm)", 10.0), _p("height", "Height (mm)", 8.0)],
        "build": lambda p: trimesh.creation.cone(radius=p["diameter"] / 2.0, height=p["height"]),
        "config": _uniform(255),
    },
]

_BY_ID = {preset["id"]: preset for preset in PRESETS}


def get_preset(preset_id: str) -> dict | None:
    return _BY_ID.get(preset_id)


def resolve_params(preset: dict, overrides: dict | None) -> dict:
    """Merge user overrides over a preset's defaults; clamp each to a sane range."""
    values = {p["key"]: float(p["default"]) for p in preset["params"]}
    floors = {p["key"]: float(p.get("min", 0.1)) for p in preset["params"]}
    for key in values:
        if overrides and key in overrides:
            try:
                values[key] = max(floors[key], min(500.0, float(overrides[key])))
            except (TypeError, ValueError):
                pass
    return values


def build_preset_mesh(preset_id: str, overrides: dict | None = None) -> trimesh.Trimesh:
    preset = _BY_ID[preset_id]
    return preset["build"](resolve_params(preset, overrides))


def mode_of(config: dict) -> str:
    grayscale = config.get("grayscale", {})
    if grayscale.get("cubic_tessellation"):
        return "cubic_tessellation"
    if grayscale.get("triangular_tessellation"):
        return "triangular_tessellation"
    if grayscale.get("gradient"):
        return "gradient"
    if grayscale.get("regions"):
        return "regions"
    return "uniform"
