"""Built-in example models, each paired with its own grayscale parameters.

Every preset bundles a procedurally generated mesh (no STL files to ship) with a
full config in the public schema, so clicking one in the UI loads the geometry
*and* dials in a showcase of one grayscale mode.
"""

from __future__ import annotations

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
        "boundary_um": 100,
        "grey_value": 128,
        "white_value": 255,
    }
    base.update(overrides)
    return _config({"cubic_tessellation": base})


def _gradient(gmin: int, gmax: int, falloff_mm: float) -> dict:
    return _config({"gradient": {"type": "edge_feather", "min": gmin, "max": gmax, "falloff_mm": falloff_mm}})


def _uniform(value: int = 255) -> dict:
    return _config({"default_solid_value": value})


# (id, name, description, mesh builder, config)
PRESETS = [
    {
        "id": "prism",
        "name": "Rectangular prism",
        # 10 mm long (X) × 7 mm wide (Y) × 4 mm tall (Z)
        "description": "10 × 7 × 4 mm — the canonical hollow-cube demo",
        "build": lambda: trimesh.creation.box(extents=[10.0, 7.0, 4.0]),
        "config": _cubic(),
    },
    {
        "id": "cube",
        "name": "Cube",
        "description": "8 mm cube — larger 8-voxel hollow cubes",
        "build": lambda: trimesh.creation.box(extents=[8.0, 8.0, 8.0]),
        "config": _cubic(cube_xy_px=8, cube_z_layers=8, grey_value=100, boundary_um=140),
    },
    {
        "id": "cylinder",
        "name": "Cylinder",
        "description": "Ø10 × 6 mm — edge-feather gradient on a round wall",
        "build": lambda: trimesh.creation.cylinder(radius=5.0, height=6.0),
        "config": _gradient(40, 255, 1.0),
    },
    {
        "id": "sphere",
        "name": "Sphere",
        "description": "Ø10 mm — soft edge-feather gradient",
        "build": lambda: trimesh.creation.icosphere(subdivisions=3, radius=5.0),
        "config": _gradient(20, 255, 1.5),
    },
    {
        "id": "torus",
        "name": "Torus",
        "description": "Ø16 ring, 4 mm tube — hollow cubes in a loop",
        "build": lambda: trimesh.creation.torus(major_radius=6.0, minor_radius=2.0),
        "config": _cubic(cap_bottom_layers=1, cap_top_layers=1, grey_value=110),
    },
    {
        "id": "cone",
        "name": "Cone",
        "description": "Ø10 × 8 mm — uniform full exposure",
        "build": lambda: trimesh.creation.cone(radius=5.0, height=8.0),
        "config": _uniform(255),
    },
]

_BY_ID = {preset["id"]: preset for preset in PRESETS}


def get_preset(preset_id: str) -> dict | None:
    return _BY_ID.get(preset_id)


def build_preset_mesh(preset_id: str) -> trimesh.Trimesh:
    return _BY_ID[preset_id]["build"]()


def mode_of(config: dict) -> str:
    grayscale = config.get("grayscale", {})
    if grayscale.get("cubic_tessellation"):
        return "cubic_tessellation"
    if grayscale.get("gradient"):
        return "gradient"
    if grayscale.get("regions"):
        return "regions"
    return "uniform"
