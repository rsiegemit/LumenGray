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
from .slicer import canvas_origin, count_layers, load_mesh, orient_mesh, slice_index
from .tessellation import tessellation_layer
from .triangulation import triangulation_layer

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
    total = count_layers(mesh, config.printer)
    if total == 0:
        raise ValueError("No layers produced; check layer height vs model Z extent")

    origin = canvas_origin(mesh, config.printer, config.center_xy)
    regions = _resolve_regions(config, origin)
    pixel_mm = config.printer.pixel_size_um / 1000.0

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
        "layer_height_um": config.printer.layer_height_um,
        "pixel_size_um": config.printer.pixel_size_um,
        "regions": len(regions),
        "rotation_deg": config.rotation_deg,
        "out_dir": out_dir,
        "mode": (
            "triangular_tessellation" if config.triangulation is not None
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
    parts = [_slug(stem) or "photostack", f"{config.printer.layer_height_um:g}um"]
    if config.triangulation is not None:
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
        parts.append(f"gradient-{g.min}-{g.max}-f{g.falloff_mm:g}")
    else:
        parts.append(f"uniform-v{config.default_solid_value}")
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


def render_layer(solid, index, total_layers, config: Config, regions, pixel_mm):
    """Build one uint8 grayscale layer. Shared by the full run and the live preview."""
    if config.triangulation is not None:
        return triangulation_layer(solid, index, total_layers, config.triangulation)
    if config.tessellation is not None:
        return tessellation_layer(solid, index, total_layers, config.tessellation)
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
