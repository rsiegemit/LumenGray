"""End-to-end pipeline: STL -> ordered grayscale PNG photostack."""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re

from PIL import Image

from .config import Config, config_to_dict

MANIFEST_FILENAME = "manifest.json"
from .geometry import shape_to_pixels
from .grayscale import base_layer, overlay_regions
from .preview import build_contact_sheet, make_thumbnail, sample_indices
from .slicer import array_mesh, canvas_origin, count_layers, load_mesh, orient_mesh, slice_index
from .grade import grade_layer, distance_depth
from .octet import octet_layer, octet_core_depth
from .tessellation import tessellation_layer
from .triangulation import triangulation_layer, tri_core_depth
from .void_connect import connect_cell, connect_components_2d

import numpy as np
from scipy import ndimage

PREVIEW_FILENAME = "_preview.png"


def run(
    stl_path: str,
    out_dir: str,
    config: Config,
    name_prefix: str = "",
    preview: bool = False,
    preview_cols: int = 8,
    preview_tiles: int = 48,
    preview_thumb_w: int = 192,
    source: dict | None = None,
) -> dict:
    """Slice, modulate, and write the stack. Returns a summary dict."""
    mesh = load_mesh(stl_path)
    mesh = orient_mesh(mesh, config.rotation_deg)
    mesh = array_mesh(mesh, config.array_count, config.array_spacing_mm)
    total = count_layers(mesh, config.printer)
    if total == 0:
        raise ValueError("No layers produced; check layer height vs model Z extent")

    origin = canvas_origin(mesh, config.printer, config.center_xy)
    regions = _resolve_regions(config, origin)
    pixel_mm = config.printer.voxel_width_um / 1000.0  # square XY pitch (width == length)

    os.makedirs(out_dir, exist_ok=True)
    pad = max(4, len(str(total)))
    preview_at = set(sample_indices(total, preview_tiles)) if preview else set()
    thumbs: list[tuple] = []

    # Slice + write one layer at a time so the full stack never lives in RAM at
    # once (holding every full-res mask is what OOMs small hosts on big models).
    for index in range(1, total + 1):
        solid = slice_index(mesh, config.printer, config.center_xy, index)
        layer = render_layer(solid, index, total, config, regions, pixel_mm)
        filename = f"{name_prefix}{index:0{pad}d}.png"
        Image.fromarray(layer, mode="L").save(os.path.join(out_dir, filename))
        if (index - 1) in preview_at:
            thumbs.append((index, make_thumbnail(layer, preview_thumb_w)))
        del solid, layer

    summary = {
        "layers": total,
        "resolution": config.printer.resolution,
        "voxel_height_um": config.printer.voxel_height_um,
        "voxel_width_um": config.printer.voxel_width_um,
        "voxel_length_um": config.printer.voxel_length_um,
        "regions": len(regions),
        "rotation_deg": config.rotation_deg,
        "out_dir": out_dir,
        "mode": (
            "octet_tessellation" if config.octet is not None
            else "triangular_tessellation" if config.triangulation is not None
            else "cubic_tessellation" if config.tessellation is not None
            else "regions"
        ),
    }
    if preview:
        preview_path = os.path.join(out_dir, PREVIEW_FILENAME)
        build_contact_sheet(thumbs, preview_cols).save(preview_path)
        summary["preview"] = preview_path

    # Metadata file for the photostack: what it was made from + every setting used.
    summary["name"] = stack_basename(config, _source_stem(source, stl_path))
    _write_manifest(out_dir, config, summary, source, stl_path)
    return summary


def _source_stem(source: dict | None, stl_path: str) -> str:
    """A human stem for naming: preset name, uploaded filename, or the STL basename."""
    if source:
        if source.get("name"):
            return str(source["name"])
        if source.get("filename"):
            return os.path.splitext(str(source["filename"]))[0]
    return os.path.splitext(os.path.basename(stl_path))[0]


def stack_basename(config: Config, stem: str) -> str:
    """A descriptive, filesystem-safe name encoding the source + grayscale parameters."""
    parts = [_slug(stem) or "photostack", f"{config.printer.voxel_height_um:g}um"]
    if config.octet is not None:
        o = config.octet
        parts.append(f"octet-xy{o.cell_xy_px}-z{o.cell_z_layers}-s{o.strut_px}-b{o.boundary_px}")
        if o.core_px:
            parts.append(f"core{o.core_px}")
    elif config.triangulation is not None:
        t = config.triangulation
        parts.append(f"tri-t{t.tri_px}-z{t.z_layers}-s{t.shell_px}-b{t.boundary_px}")
        if t.core_px:
            parts.append(f"core{t.core_px}")
    elif config.tessellation is not None:
        t = config.tessellation
        parts.append(f"cubic-xy{t.cube_xy_px}-z{t.cube_z_layers}-s{t.shell_px}-b{t.boundary_px}")
        if t.core_px:
            parts.append(f"core{t.core_px}")
    elif config.gradient is not None:
        g = config.gradient
        parts.append(f"gradient-{g.mode}" + (f"-{g.axis}" if g.mode == "linear" else ""))
    else:
        parts.append(f"uniform-v{config.default_solid_value}")
    if config.grade is not None:
        parts.append(f"grade-{config.grade.interp[:3]}{len(config.grade.stops)}")
    if config.gyroid is not None:
        parts.append(f"gyroid-c{config.gyroid.cell_mm:g}-w{config.gyroid.channel_px}")
    if any(config.rotation_deg):
        parts.append("rot" + "x".join(f"{v:g}" for v in config.rotation_deg))
    return "_".join(parts)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.+-]+", "-", str(text).strip()).strip("-")


def _write_manifest(out_dir, config, summary, source, stl_path) -> None:
    cfg = config_to_dict(config)
    manifest = {
        "generator": "LumenGray",
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "name": summary["name"],
        "source": source or {"kind": "upload", "filename": os.path.basename(stl_path)},
        "layers": summary["layers"],
        "mode": summary["mode"],
        "printer": cfg["printer"],
        "model": cfg["model"],
        "grayscale": cfg["grayscale"],
    }
    with open(os.path.join(out_dir, MANIFEST_FILENAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


_VOID_CACHE: dict = {}


def _cache_get(sig, builder):
    """Memoize a connector build, bounded so interactive param tweaks (each a new
    signature) don't accumulate full-resolution masks forever."""
    if sig not in _VOID_CACHE:
        if len(_VOID_CACHE) >= 16:
            _VOID_CACHE.pop(next(iter(_VOID_CACHE)))
        _VOID_CACHE[sig] = builder()
    return _VOID_CACHE[sig]


def _cell_void_volume(config: Config):
    """One unit cell's 3D void mask (cz, cx, cx) for a tessellation mode, including
    per-element grade. A voxel is void when its exposure <= ``connect_voids.void_max``
    (0 = only fully-black). Returns (V, cx, cz, cap_bottom, cap_top) or None if no
    periodic tessellation is active."""
    vm = config.gyroid.void_max if config.gyroid is not None else 0
    if config.octet is not None:
        o = config.octet
        cx, cz = o.cell_xy_px, o.cell_z_layers
        oc = dataclasses.replace(o, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0)
        solid = np.ones((cx, cx), dtype=bool)
        V = np.zeros((cz, cx, cx), dtype=bool)
        for zc in range(cz):
            lay = octet_layer(solid, zc + 1, cz, oc)
            if config.grade is not None:
                lay = grade_layer(lay, solid, config.grade, octet_core_depth(solid.shape, zc, oc))
            V[zc] = lay <= vm
        return V, cx, cz, o.cap_bottom_layers, o.cap_top_layers
    if config.tessellation is not None:
        t = config.tessellation
        cx, cz = t.cube_xy_px, t.cube_z_layers
        tc = dataclasses.replace(t, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0)
        solid = np.ones((cx, cx), dtype=bool)
        V = np.zeros((cz, cx, cx), dtype=bool)
        for zc in range(cz):
            lay = tessellation_layer(solid, zc + 1, cz, tc)
            if config.grade is not None:
                lay = grade_layer(lay, solid, config.grade, distance_depth(lay, tc.cube_xy_px / 2.0))
            V[zc] = lay <= vm
        return V, cx, cz, t.cap_bottom_layers, t.cap_top_layers
    return None  # triangular / non-tessellation: fall back to the legacy gyroid


def _void_connector(config: Config):
    """Cached (channels K (cz,cx,cx), cx, cz, cap_bottom, cap_top) for the active
    cell, or None (no periodic cell → the mode isn't supported yet). Both routes
    (geodesic + tpms) connect the real voids here; route only shapes the channel."""
    g = config.gyroid
    if g is None:
        return None
    base = config.octet if config.octet is not None else config.tessellation
    sig = (repr(base), repr(config.grade), g.channel_px, g.route, g.void_max)

    def build():
        vol = _cell_void_volume(config)
        if vol is None or not vol[0].any():
            return None
        V, cx, cz, cap_b, cap_t = vol
        return (connect_cell(V, g.channel_px, g.route), cx, cz, cap_b, cap_t)

    return _cache_get(sig, build)


def _triangular_channels(config: Config, shape):
    """Cached 2D channel mask connecting every triangular void (cores + graded
    shells) into one network. Triangular row spacing is irrational, so it isn't
    integer-tileable — but its void pattern is layer-independent (a Z-column), so we
    connect it once in 2D (union over a Z-period) and extrude. None if no voids."""
    g = config.gyroid
    sig = ("tri", repr(config.triangulation), repr(config.grade), g.channel_px, g.route, g.void_max, shape)

    def build():
        t = config.triangulation
        tc = dataclasses.replace(t, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0)
        full = np.ones(shape, dtype=bool)
        V2 = np.zeros(shape, dtype=bool)
        for zc in range(t.z_layers):  # union over a Z-period → the full void footprint
            lay = triangulation_layer(full, zc + 1, t.z_layers, tc)
            if config.grade is not None:
                lay = grade_layer(lay, full, config.grade, tri_core_depth(shape, tc))
            V2 |= lay <= g.void_max
        # Cap bridges at ~1.5 triangle edges: enough to link neighbouring cell voids,
        # but far too short to draw a channel across the whole part from sparse voids.
        max_bridge = t.tri_px * 1.5
        return connect_components_2d(V2, g.channel_px, g.route, max_bridge) if V2.any() else None

    return _cache_get(sig, build)


def _void_connect_carve(layer, solid, layer_index, total_layers, config: Config):
    """Carve the connecting channels. Cubic/octet tile a unit cell's channel pattern;
    triangular extrudes a 2D-connected pattern; both void it inside the part."""
    g = config.gyroid
    if config.triangulation is not None:  # extrude the 2D void-connection network
        t = config.triangulation
        z = layer_index - 1 - t.cap_bottom_layers
        if z < 0 or layer_index > total_layers - t.cap_top_layers:
            return layer
        chan = _triangular_channels(config, layer.shape)
        if chan is None:
            return layer
        interior = solid if (g.drain or g.skin_px <= 0) else ndimage.distance_transform_edt(solid) > g.skin_px
        return np.where(interior & (chan | (layer <= g.void_max)), np.uint8(0), layer)
    conn = _void_connector(config)
    if conn is None:
        # A tessellation with no voids has nothing to connect.
        if config.octet is not None or config.tessellation is not None:
            return layer
        # Non-periodic (gradient / uniform / regions): no tileable cell, so connect
        # THIS layer's real voids directly in 2D. The gradient field is smooth, so
        # neighbouring layers' channels overlap and the network joins through Z;
        # concentric void shells (a void→light→void ramp) bridge radially. No
        # bridge cap here — the point is to match EVERY void, even across a bright
        # band — and a smooth field yields clean nested shells, not scattered noise.
        voids = (layer <= g.void_max) & solid
        if not voids.any():
            return layer
        chan = connect_components_2d(voids, g.channel_px, g.route)
        interior = solid if (g.drain or g.skin_px <= 0) else ndimage.distance_transform_edt(solid) > g.skin_px
        return np.where(interior & (chan | (layer <= g.void_max)), np.uint8(0), layer)
    K, cx, cz, cap_b, cap_t = conn
    z = layer_index - 1 - cap_b  # 0 at the first interior layer
    if z < 0 or layer_index > total_layers - cap_t:  # solid caps: no channels
        return layer
    kz = K[z % cz]  # this cell-layer's channel pattern (cx, cx)
    height, width = layer.shape
    chan = np.tile(kz, (-(-height // cx), -(-width // cx)))[:height, :width]
    g = config.gyroid
    if g.drain or g.skin_px <= 0:
        interior = solid  # reach the outer surface (drains)
    else:
        interior = ndimage.distance_transform_edt(solid) > g.skin_px  # keep a solid skin
    return np.where(interior & chan, np.uint8(0), layer)


def render_layer(solid, index, total_layers, config: Config, regions, pixel_mm):
    """Build one uint8 grayscale layer. Shared by the full run and the live preview."""
    if config.octet is not None:
        layer = octet_layer(solid, index, total_layers, config.octet)
    elif config.triangulation is not None:
        layer = triangulation_layer(solid, index, total_layers, config.triangulation)
    elif config.tessellation is not None:
        layer = tessellation_layer(solid, index, total_layers, config.tessellation)
    else:
        layer = overlay_regions(base_layer(solid, config.gradient, config.default_solid_value, index, total_layers), solid, index, regions)
    if config.grade is not None:  # structure->core gradient (tessellation cells only)
        if config.octet is not None:
            z = index - 1 - config.octet.cap_bottom_layers  # 0 at first interior layer
            depth = octet_core_depth(solid.shape, z, config.octet)
        elif config.triangulation is not None:
            depth = tri_core_depth(solid.shape, config.triangulation)
        elif config.tessellation is not None:
            depth = distance_depth(layer, config.tessellation.cube_xy_px / 2.0)
        else:
            depth = None
        layer = grade_layer(layer, solid, config.grade, depth)
    if config.gyroid is not None:  # overlay: connect every void into one network
        layer = _void_connect_carve(layer, solid, index, total_layers, config)
    return layer


def resolve_regions(config: Config, origin) -> tuple:
    return _resolve_regions(config, origin)


def _resolve_regions(config: Config, origin) -> tuple:
    """Convert any mm-unit regions to pixel coordinates; pixel regions pass through."""
    resolved = []
    for region in config.regions:
        if region.units == "mm":
            shape = shape_to_pixels(
                region.shape, origin, config.printer.voxel_width_um / 1000.0, config.printer.resolution
            )
            region = dataclasses.replace(region, shape=shape, units="px")
        resolved.append(region)
    return tuple(resolved)
