"""Configuration loading and validation.

The config mirrors the Lumen X3 protocol:
  - printer specs (step 1, Chitubox machine settings) become parameters
  - grayscale regions (step 3, ImageJ selections) become scripted rules
All data is immutable (frozen dataclasses + tuples).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

# Lumen X3 optical specs from Protocol.pdf, used as defaults.
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_VOXEL_WIDTH_UM = 35.0   # X (column) voxel pitch
DEFAULT_VOXEL_LENGTH_UM = 35.0  # Y (row) voxel pitch
DEFAULT_VOXEL_HEIGHT_UM = 50.0  # Z (layer) voxel pitch; protocol offers 20 / 50 / 100
SUPPORTED_VOXEL_HEIGHTS_UM = (20.0, 50.0, 100.0)
SHAPE_TYPES = ("rect", "circle", "polygon")
UNIT_TYPES = ("px", "mm")
GRADIENT_TYPES = ("edge_feather",)
DEFAULT_FALLOFF_MM = 0.35

# Cubic-tessellation defaults (everything in voxel counts).
DEFAULT_TESSELLATION = {
    "cap_bottom_layers": 2,
    "cap_top_layers": 2,
    "cube_xy_px": 6,
    "cube_z_layers": 6,
    "shell_px": 1,
    "core_px": 0,
    "boundary_px": 3,
    "grey_value": 128,
    "white_value": 255,
}

# Triangular (Buckminster-Fuller-style) tessellation defaults (voxel counts).
DEFAULT_TRIANGULAR = {
    "cap_bottom_layers": 2,
    "cap_top_layers": 2,
    "tri_px": 10,  # triangle edge length in XY pixels
    "z_layers": 6,  # spacing between horizontal triangular frames, in Z layers
    "shell_px": 1,
    "core_px": 0,
    "boundary_px": 3,
    "grey_value": 128,
    "white_value": 255,
}

# Octet-truss (Fuller octetruss) tessellation defaults (voxel counts).
DEFAULT_OCTET = {
    "cap_bottom_layers": 2,
    "cap_top_layers": 2,
    "cell_xy_px": 14,  # FCC cube-cell edge in XY pixels (node spacing = half)
    "cell_z_layers": 10,  # FCC cube-cell edge in Z layers (node spacing = half)
    "strut_px": 1,
    "core_px": 0,  # black void in each cell's deep interior (0 = none)
    "boundary_px": 3,
    "grey_value": 128,
    "white_value": 255,
}

# Gyroid void-connector overlay defaults (composes on top of any grayscale mode).
DEFAULT_GYROID = {
    "cell_mm": 0.8,  # gyroid unit-cell period (mm) — perfusion channel spacing
    "channel_px": 4,  # carved void channel width (voxels) along the gyroid surface
    "skin_px": 3,  # solid wall kept around the part boundary (void never breaches it)
}

# Structure->core exposure gradient defaults (grades tessellation cells by distance).
DEFAULT_GRADE = {
    "stops": [[0.0, 255], [1.0, 0]],  # ramp control points: (distance 0=struts..1=core, value)
    "interp": "linear",  # "linear" (continuous) or "step" (piecewise)
}


class ConfigError(ValueError):
    """Raised when a config file is malformed."""


@dataclass(frozen=True)
class Printer:
    resolution: tuple  # (width_px, height_px)
    voxel_width_um: float   # X (column) voxel pitch, microns
    voxel_length_um: float  # Y (row) voxel pitch, microns
    voxel_height_um: float  # Z (layer) voxel pitch, microns


@dataclass(frozen=True)
class Region:
    name: str
    value: int  # grayscale 0-255 (R=G=B)
    shape: dict
    units: str  # "px" (output-PNG pixels) or "mm" (model/world coords)
    layers: tuple | None  # (start, end) inclusive, 1-indexed; None = all layers
    clip_to_solid: bool  # only modulate cured (solid) pixels


@dataclass(frozen=True)
class Gradient:
    type: str  # "edge_feather"
    min: int  # gray at the edge (distance 0)
    max: int  # gray once distance >= falloff_mm into the solid
    falloff_mm: float  # ramp distance from min to max


@dataclass(frozen=True)
class CubicTessellation:
    """Hollow-cube infill mode (replaces the base fill when present).

    Reasoned about in voxels: one voxel is an output pixel in XY and one
    photostack layer in Z. With 35um XY pixels and 50um layers the voxels -
    and the cubes - are only approximately cubic, which is expected.
    """

    cap_bottom_layers: int  # solid-white layers at the bottom of the stack
    cap_top_layers: int  # solid-white layers at the top of the stack
    cube_xy_px: int  # cube edge in XY pixels
    cube_z_layers: int  # cube edge in Z layers
    shell_px: int  # white shell thickness (voxels) on every face; core = cube - 2*shell
    core_px: int  # black (void) cube in each cell's centre, this many voxels per side (0 = none)
    boundary_px: int  # per-layer white rim: solid within this many px (L-inf) of an edge
    grey_value: int  # fill for the hollow cube core
    white_value: int  # fill for shells, rim, and caps


@dataclass(frozen=True)
class TriangularTessellation:
    """Buckminster-Fuller-style triangular strut infill (replaces the base fill).

    A triangular grid in XY (three line families at 60 deg) gives vertical white
    columns at the grid nodes, braced by horizontal triangular frames every
    `z_layers`; triangle faces and the core stay grey.
    """

    cap_bottom_layers: int  # solid-white layers at the bottom of the stack
    cap_top_layers: int  # solid-white layers at the top of the stack
    tri_px: int  # triangle edge length in XY pixels
    z_layers: int  # spacing between horizontal triangular frames, in Z layers
    shell_px: int  # white strut thickness (voxels)
    core_px: int  # black (void) core in each cell's centre, this many voxels (0 = none)
    boundary_px: int  # per-layer white rim: solid within this many px (L-inf) of an edge
    grey_value: int  # fill for the triangle faces / core
    white_value: int  # fill for struts, rim, and caps


@dataclass(frozen=True)
class OctetTessellation:
    """Octet-truss infill — space-filling tetrahedra + octahedra (FCC strut
    lattice). Sloped struts between layers make true 3D pyramids, unlike the
    triangular *prism* mode. Reasoned about in voxels (XY pixel, Z layer)."""

    cap_bottom_layers: int  # solid-white layers at the bottom
    cap_top_layers: int  # solid-white layers at the top
    cell_xy_px: int  # FCC cube-cell edge in XY pixels (node spacing = half this)
    cell_z_layers: int  # FCC cube-cell edge in Z layers (node spacing = half this)
    strut_px: int  # white strut radius (voxels)
    core_px: int  # black (void) core carved in each cell's deep interior (0 = none)
    boundary_px: int  # per-layer white rim: solid within this many px (L-inf) of an edge
    grey_value: int  # fill for the truss faces / core
    white_value: int  # fill for struts, rim, and caps


@dataclass(frozen=True)
class GyroidChannel:
    """Gyroid void-connector overlay — carves a continuous minimal-surface void
    through whatever the base grayscale mode produced, threading isolated black
    (lumen) regions into one interconnected, drainable perfusion network."""

    cell_mm: float  # gyroid unit-cell period in mm (isotropic in printed space)
    channel_px: int  # carved void channel width, in voxels
    skin_px: int  # solid wall kept around the boundary; the void never crosses it


@dataclass(frozen=True)
class Grade:
    """Structure->core exposure gradient for tessellation cells: grade by distance
    from the white struts inward via a designable ramp of (distance, value) stops
    — white at the structure to black at the cell core, ``linear`` (continuous) or
    ``step`` (piecewise) between stops."""

    stops: tuple  # ascending (pos in [0,1], value in [0,255]) control points
    interp: str  # "linear" | "step"


@dataclass(frozen=True)
class Config:
    printer: Printer
    default_solid_value: int  # fill value for cured pixels (255 = full exposure)
    gradient: Gradient | None  # geometry-driven base fill; regions overlay on top
    center_xy: bool
    rotation_deg: tuple  # (x, y, z) degrees applied before slicing
    regions: tuple
    tessellation: CubicTessellation | None  # hollow-cube infill; overrides gradient+regions
    triangulation: TriangularTessellation | None  # triangular strut infill; overrides the above
    octet: OctetTessellation | None  # octet-truss infill; overrides the above
    gyroid: GyroidChannel | None  # gyroid void-connector overlay (composes on any mode)
    grade: Grade | None  # structure->core exposure gradient for tessellation cells


def default_config() -> Config:
    """Config with Lumen X3 defaults and no grayscale regions (uniform masks)."""
    return Config(
        printer=Printer(DEFAULT_RESOLUTION, DEFAULT_VOXEL_WIDTH_UM, DEFAULT_VOXEL_LENGTH_UM, DEFAULT_VOXEL_HEIGHT_UM),
        default_solid_value=255,
        gradient=None,
        center_xy=True,
        rotation_deg=(0.0, 0.0, 0.0),
        regions=(),
        tessellation=None,
        triangulation=None,
        octet=None,
        gyroid=None,
        grade=None,
    )


def default_tessellation() -> CubicTessellation:
    """The default hollow-cube infill (matches DEFAULT_TESSELLATION)."""
    return CubicTessellation(**DEFAULT_TESSELLATION)


def default_triangular() -> TriangularTessellation:
    """The default triangular strut infill (matches DEFAULT_TRIANGULAR)."""
    return TriangularTessellation(**DEFAULT_TRIANGULAR)


def default_octet() -> OctetTessellation:
    """The default octet-truss infill (matches DEFAULT_OCTET)."""
    return OctetTessellation(**DEFAULT_OCTET)


def default_gyroid() -> GyroidChannel:
    """The default gyroid void-connector overlay (matches DEFAULT_GYROID)."""
    return GyroidChannel(**DEFAULT_GYROID)


def default_grade() -> Grade:
    """The default structure->core exposure gradient (matches DEFAULT_GRADE)."""
    return Grade(stops=tuple(tuple(s) for s in DEFAULT_GRADE["stops"]), interp=DEFAULT_GRADE["interp"])


def load_config(path: str) -> Config:
    """Load and validate a JSON config file, falling back to defaults per field."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"Config file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a JSON object")
    return _build_config(raw)


def config_from_dict(raw: dict) -> Config:
    """Build and validate a Config from an in-memory dict (e.g. an API request body)."""
    if not isinstance(raw, dict):
        raise ConfigError("Config must be a JSON object")
    return _build_config(raw)


def config_to_dict(config: Config) -> dict:
    """Serialize a validated Config back to the public schema (the values actually used)."""
    grayscale: dict = {}
    if config.octet is not None:
        grayscale["octet_tessellation"] = asdict(config.octet)
    elif config.triangulation is not None:
        grayscale["triangular_tessellation"] = asdict(config.triangulation)
    elif config.tessellation is not None:
        grayscale["cubic_tessellation"] = asdict(config.tessellation)
    else:
        if config.gradient is not None:
            grayscale["gradient"] = asdict(config.gradient)
        else:
            grayscale["default_solid_value"] = config.default_solid_value
        if config.regions:
            grayscale["regions"] = [asdict(region) for region in config.regions]
    if config.gyroid is not None:  # overlay — independent of the base mode
        grayscale["connect_voids"] = asdict(config.gyroid)
    if config.grade is not None:  # structure->core gradient (tessellation cells)
        grayscale["grade"] = asdict(config.grade)
    return {
        "printer": {
            "resolution": list(config.printer.resolution),
            "voxel_width_um": config.printer.voxel_width_um,
            "voxel_length_um": config.printer.voxel_length_um,
            "voxel_height_um": config.printer.voxel_height_um,
        },
        "model": {"center_xy": config.center_xy, "rotation_deg": list(config.rotation_deg)},
        "grayscale": grayscale,
    }


def _build_config(raw: dict) -> Config:
    base = default_config()
    printer = _build_printer(raw.get("printer", {}), base.printer)
    grayscale = raw.get("grayscale", {})
    if not isinstance(grayscale, dict):
        raise ConfigError("'grayscale' must be an object")
    default_solid_value = _validate_value(
        grayscale.get("default_solid_value", base.default_solid_value),
        "grayscale.default_solid_value",
    )
    gradient = _build_gradient(grayscale.get("gradient"))
    regions = tuple(
        _build_region(item, index)
        for index, item in enumerate(grayscale.get("regions", []))
    )
    tessellation = _build_tessellation(grayscale.get("cubic_tessellation"))
    triangulation = _build_triangular(grayscale.get("triangular_tessellation"))
    octet = _build_octet(grayscale.get("octet_tessellation"))
    gyroid = _build_gyroid(grayscale.get("connect_voids"))
    grade = _build_grade(grayscale.get("grade"))
    model = raw.get("model", {})
    center_xy = bool(model.get("center_xy", base.center_xy))
    rotation = _validate_rotation(model.get("rotation_deg", base.rotation_deg))
    return Config(
        printer, default_solid_value, gradient, center_xy, rotation, regions, tessellation, triangulation, octet, gyroid, grade
    )


def _validate_rotation(rotation) -> tuple:
    if (
        not isinstance(rotation, (list, tuple))
        or len(rotation) != 3
        or not all(isinstance(value, (int, float)) for value in rotation)
    ):
        raise ConfigError("model.rotation_deg must be [x, y, z] degrees (three numbers)")
    return tuple(float(value) for value in rotation)


def _build_gradient(raw) -> Gradient | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.gradient' must be an object")
    gtype = raw.get("type", "edge_feather")
    if gtype not in GRADIENT_TYPES:
        raise ConfigError(f"grayscale.gradient.type must be one of {GRADIENT_TYPES}")
    gmin = _validate_value(raw.get("min", 40), "grayscale.gradient.min")
    gmax = _validate_value(raw.get("max", 255), "grayscale.gradient.max")
    if gmin > gmax:
        raise ConfigError("grayscale.gradient.min must be <= max")
    falloff = _positive_number(
        raw.get("falloff_mm", DEFAULT_FALLOFF_MM), "grayscale.gradient.falloff_mm"
    )
    return Gradient(gtype, gmin, gmax, falloff)


def _build_tessellation(raw) -> CubicTessellation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.cubic_tessellation' must be an object")
    if raw.get("enabled") is False:
        return None

    def _int(key: str, minimum: int) -> int:
        value = raw.get(key, DEFAULT_TESSELLATION[key])
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ConfigError(
                f"grayscale.cubic_tessellation.{key} must be an integer >= {minimum}"
            )
        return value

    cube_xy = _int("cube_xy_px", 1)
    cube_z = _int("cube_z_layers", 1)
    shell = _int("shell_px", 1)
    if 2 * shell >= min(cube_xy, cube_z):
        raise ConfigError(
            "grayscale.cubic_tessellation.shell_px too large: leaves no grey core "
            "(need 2*shell_px < cube_xy_px and < cube_z_layers)"
        )
    boundary = _int("boundary_px", 0)
    grey = _validate_value(
        raw.get("grey_value", DEFAULT_TESSELLATION["grey_value"]),
        "grayscale.cubic_tessellation.grey_value",
    )
    white = _validate_value(
        raw.get("white_value", DEFAULT_TESSELLATION["white_value"]),
        "grayscale.cubic_tessellation.white_value",
    )
    return CubicTessellation(
        cap_bottom_layers=_int("cap_bottom_layers", 0),
        cap_top_layers=_int("cap_top_layers", 0),
        cube_xy_px=cube_xy,
        cube_z_layers=cube_z,
        shell_px=shell,
        core_px=_int("core_px", 0),
        boundary_px=boundary,
        grey_value=grey,
        white_value=white,
    )


def _build_triangular(raw) -> TriangularTessellation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.triangular_tessellation' must be an object")
    if raw.get("enabled") is False:
        return None

    def _int(key: str, minimum: int) -> int:
        value = raw.get(key, DEFAULT_TRIANGULAR[key])
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ConfigError(
                f"grayscale.triangular_tessellation.{key} must be an integer >= {minimum}"
            )
        return value

    tri = _int("tri_px", 3)
    z_layers = _int("z_layers", 1)
    shell = _int("shell_px", 1)
    if 2 * shell >= tri:
        raise ConfigError(
            "grayscale.triangular_tessellation.shell_px too large for tri_px (need 2*shell_px < tri_px)"
        )
    grey = _validate_value(
        raw.get("grey_value", DEFAULT_TRIANGULAR["grey_value"]),
        "grayscale.triangular_tessellation.grey_value",
    )
    white = _validate_value(
        raw.get("white_value", DEFAULT_TRIANGULAR["white_value"]),
        "grayscale.triangular_tessellation.white_value",
    )
    return TriangularTessellation(
        cap_bottom_layers=_int("cap_bottom_layers", 0),
        cap_top_layers=_int("cap_top_layers", 0),
        tri_px=tri,
        z_layers=z_layers,
        shell_px=shell,
        core_px=_int("core_px", 0),
        boundary_px=_int("boundary_px", 0),
        grey_value=grey,
        white_value=white,
    )


def _build_octet(raw) -> OctetTessellation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.octet_tessellation' must be an object")
    if raw.get("enabled") is False:
        return None

    def _int(key: str, minimum: int) -> int:
        value = raw.get(key, DEFAULT_OCTET[key])
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ConfigError(f"grayscale.octet_tessellation.{key} must be an integer >= {minimum}")
        return value

    cell_xy = _int("cell_xy_px", 2)
    cell_z = _int("cell_z_layers", 2)
    strut = _int("strut_px", 1)
    if 2 * strut >= min(cell_xy, cell_z):
        raise ConfigError(
            "grayscale.octet_tessellation.strut_px too large: leaves no grey core "
            "(need 2*strut_px < cell_xy_px and < cell_z_layers)"
        )
    grey = _validate_value(raw.get("grey_value", DEFAULT_OCTET["grey_value"]), "grayscale.octet_tessellation.grey_value")
    white = _validate_value(raw.get("white_value", DEFAULT_OCTET["white_value"]), "grayscale.octet_tessellation.white_value")
    return OctetTessellation(
        cap_bottom_layers=_int("cap_bottom_layers", 0),
        cap_top_layers=_int("cap_top_layers", 0),
        cell_xy_px=cell_xy,
        cell_z_layers=cell_z,
        strut_px=strut,
        core_px=_int("core_px", 0),
        boundary_px=_int("boundary_px", 0),
        grey_value=grey,
        white_value=white,
    )


def _build_gyroid(raw) -> GyroidChannel | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.connect_voids' must be an object")
    if raw.get("enabled") is False:
        return None
    cell_mm = _positive_number(raw.get("cell_mm", DEFAULT_GYROID["cell_mm"]), "grayscale.connect_voids.cell_mm")
    channel = raw.get("channel_px", DEFAULT_GYROID["channel_px"])
    if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1:
        raise ConfigError("grayscale.connect_voids.channel_px must be an integer >= 1")
    skin = raw.get("skin_px", DEFAULT_GYROID["skin_px"])
    if not isinstance(skin, int) or isinstance(skin, bool) or skin < 0:
        raise ConfigError("grayscale.connect_voids.skin_px must be an integer >= 0")
    return GyroidChannel(cell_mm=cell_mm, channel_px=channel, skin_px=skin)


def _build_grade(raw) -> Grade | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("'grayscale.grade' must be an object")
    if raw.get("enabled") is False:
        return None
    interp = raw.get("interp", DEFAULT_GRADE["interp"])
    if interp not in ("linear", "step"):
        raise ConfigError("grayscale.grade.interp must be 'linear' or 'step'")
    raw_stops = raw.get("stops", DEFAULT_GRADE["stops"])
    if not isinstance(raw_stops, list) or len(raw_stops) < 2:
        raise ConfigError("grayscale.grade.stops must be a list of at least 2 [pos, value] pairs")
    stops = []
    for item in raw_stops:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ConfigError("each grayscale.grade stop must be [pos, value]")
        pos, value = item
        if not isinstance(pos, (int, float)) or isinstance(pos, bool) or not (0.0 <= pos <= 1.0):
            raise ConfigError("grayscale.grade stop pos must be a number in [0, 1]")
        stops.append((float(pos), _validate_value(value, "grayscale.grade stop value")))
    stops.sort()
    return Grade(stops=tuple(stops), interp=interp)


def _build_printer(raw: dict, base: Printer) -> Printer:
    if not isinstance(raw, dict):
        raise ConfigError("'printer' must be an object")
    resolution = raw.get("resolution", list(base.resolution))
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) != 2
        or not all(isinstance(value, int) and value > 0 for value in resolution)
    ):
        raise ConfigError("printer.resolution must be [width, height] positive integers")
    renamed = {"pixel_size_um", "layer_height_um"} & set(raw)
    if renamed:
        raise ConfigError(
            f"printer key(s) {sorted(renamed)} were renamed — use "
            "voxel_width_um / voxel_length_um (XY, µm) and voxel_height_um (Z, µm)"
        )
    width = _positive_number(raw.get("voxel_width_um", base.voxel_width_um), "printer.voxel_width_um")
    length = _positive_number(raw.get("voxel_length_um", base.voxel_length_um), "printer.voxel_length_um")
    height = _positive_number(raw.get("voxel_height_um", base.voxel_height_um), "printer.voxel_height_um")
    if height not in SUPPORTED_VOXEL_HEIGHTS_UM:
        # Allowed, but the protocol only documents 20/50/100 µm.
        print(f"[config] warning: voxel_height_um={height} is outside protocol values {SUPPORTED_VOXEL_HEIGHTS_UM}")
    return Printer((int(resolution[0]), int(resolution[1])), float(width), float(length), float(height))


def _build_region(raw: dict, index: int) -> Region:
    if not isinstance(raw, dict):
        raise ConfigError(f"grayscale.regions[{index}] must be an object")
    name = str(raw.get("name", f"region{index}"))
    value = _validate_value(raw.get("value"), f"grayscale.regions[{index}].value")
    shape = _validate_shape(raw.get("shape"), index)
    units = raw.get("units", "px")
    if units not in UNIT_TYPES:
        raise ConfigError(f"grayscale.regions[{index}].units must be one of {UNIT_TYPES}")
    layers = _validate_layers(raw.get("layers"), index)
    clip = bool(raw.get("clip_to_solid", True))
    return Region(name=name, value=value, shape=shape, units=units, layers=layers, clip_to_solid=clip)


def _validate_shape(shape, index: int) -> dict:
    if not isinstance(shape, dict) or shape.get("type") not in SHAPE_TYPES:
        raise ConfigError(
            f"grayscale.regions[{index}].shape.type must be one of {SHAPE_TYPES}"
        )
    kind = shape["type"]
    required = {
        "rect": ("x", "y", "w", "h"),
        "circle": ("cx", "cy", "r"),
        "polygon": ("points",),
    }[kind]
    missing = [key for key in required if key not in shape]
    if missing:
        raise ConfigError(f"grayscale.regions[{index}].shape ({kind}) missing keys: {missing}")
    if kind == "polygon":
        points = shape["points"]
        if not isinstance(points, list) or len(points) < 3:
            raise ConfigError(f"grayscale.regions[{index}].shape.points needs >= 3 [x, y] pairs")
    return dict(shape)


def _validate_layers(layers, index: int) -> tuple | None:
    if layers is None:
        return None
    if (
        not isinstance(layers, (list, tuple))
        or len(layers) != 2
        or not all(isinstance(value, int) and value >= 1 for value in layers)
        or layers[0] > layers[1]
    ):
        raise ConfigError(
            f"grayscale.regions[{index}].layers must be [start, end] 1-indexed with start <= end"
        )
    return (int(layers[0]), int(layers[1]))


def _validate_value(value, label: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ConfigError(f"{label} must be an integer 0-255")
    return value


def _positive_number(value, label: str) -> float:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{label} must be a positive number")
    return float(value)
