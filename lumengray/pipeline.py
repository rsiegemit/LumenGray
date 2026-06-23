"""End-to-end pipeline: STL -> ordered grayscale PNG photostack."""

from __future__ import annotations

import dataclasses
import os

from PIL import Image

from .config import Config
from .geometry import shape_to_pixels
from .grayscale import base_layer, overlay_regions
from .preview import build_contact_sheet, make_thumbnail, sample_indices
from .slicer import canvas_origin, load_mesh, orient_mesh, slice_mesh
from .tessellation import tessellation_layer

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
) -> dict:
    """Slice, modulate, and write the stack. Returns a summary dict."""
    mesh = load_mesh(stl_path)
    mesh = orient_mesh(mesh, config.rotation_deg)
    solids = slice_mesh(mesh, config.printer, config.center_xy)
    if not solids:
        raise ValueError("No layers produced; check layer height vs model Z extent")

    origin = canvas_origin(mesh, config.printer, config.center_xy)
    regions = _resolve_regions(config, origin)
    pixel_mm = config.printer.pixel_size_um / 1000.0

    os.makedirs(out_dir, exist_ok=True)
    pad = max(4, len(str(len(solids))))
    preview_at = set(sample_indices(len(solids), preview_tiles)) if preview else set()
    thumbs: list[tuple] = []

    for index, solid in enumerate(solids, start=1):
        layer = render_layer(solid, index, len(solids), config, regions, pixel_mm)
        filename = f"{name_prefix}{index:0{pad}d}.png"
        Image.fromarray(layer, mode="L").save(os.path.join(out_dir, filename))
        if (index - 1) in preview_at:
            thumbs.append((index, make_thumbnail(layer, preview_thumb_w)))

    summary = {
        "layers": len(solids),
        "resolution": config.printer.resolution,
        "layer_height_um": config.printer.layer_height_um,
        "pixel_size_um": config.printer.pixel_size_um,
        "regions": len(regions),
        "rotation_deg": config.rotation_deg,
        "out_dir": out_dir,
        "mode": "cubic_tessellation" if config.tessellation is not None else "regions",
    }
    if preview:
        preview_path = os.path.join(out_dir, PREVIEW_FILENAME)
        build_contact_sheet(thumbs, preview_cols).save(preview_path)
        summary["preview"] = preview_path
    return summary


def render_layer(solid, index, total_layers, config: Config, regions, pixel_mm):
    """Build one uint8 grayscale layer. Shared by the full run and the live preview."""
    if config.tessellation is not None:
        return tessellation_layer(
            solid, index, total_layers, config.tessellation, config.printer.pixel_size_um
        )
    layer = base_layer(solid, config.gradient, config.default_solid_value, pixel_mm)
    return overlay_regions(layer, solid, index, regions)


def resolve_regions(config: Config, origin) -> tuple:
    return _resolve_regions(config, origin)


def _resolve_regions(config: Config, origin) -> tuple:
    """Convert any mm-unit regions to pixel coordinates; pixel regions pass through."""
    resolved = []
    for region in config.regions:
        if region.units == "mm":
            shape = shape_to_pixels(
                region.shape, origin, config.printer.pixel_size_um / 1000.0, config.printer.resolution
            )
            region = dataclasses.replace(region, shape=shape, units="px")
        resolved.append(region)
    return tuple(resolved)
