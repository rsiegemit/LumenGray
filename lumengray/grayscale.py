"""Build grayscale layers from binary masks.

Replaces protocol step 3 (ImageJ select + fill). A base fill (flat value or a
geometry-driven gradient) is computed for cured pixels, then config regions are
rasterized and overlaid on top.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from .config import Gradient


def base_layer(
    solid: np.ndarray,
    gradient: Gradient | None,
    default_solid_value: int,
    pixel_mm: float,
) -> np.ndarray:
    """Return the uint8 base fill for cured pixels (background stays 0)."""
    if gradient is None:
        return np.where(solid, np.uint8(default_solid_value), 0).astype(np.uint8)
    return _edge_feather(solid, gradient, pixel_mm)


def _edge_feather(solid: np.ndarray, gradient: Gradient, pixel_mm: float) -> np.ndarray:
    """Gray = min..max by distance to the nearest edge (outer wall or any hole)."""
    distance_mm = ndimage.distance_transform_edt(solid) * pixel_mm
    fraction = np.clip(distance_mm / gradient.falloff_mm, 0.0, 1.0)
    values = gradient.min + (gradient.max - gradient.min) * fraction
    return np.where(solid, np.round(values), 0).astype(np.uint8)


def overlay_regions(
    layer: np.ndarray,
    solid: np.ndarray,
    layer_index: int,  # 1-indexed
    regions: tuple,
) -> np.ndarray:
    """Overlay config regions onto an existing base layer (later regions win)."""
    for region in regions:
        if not _layer_in_range(layer_index, region.layers):
            continue
        target = _shape_mask(region.shape, solid.shape)
        if region.clip_to_solid:
            target = target & solid
        layer = np.where(target, np.uint8(region.value), layer)
    return layer


def _layer_in_range(layer_index: int, layers: tuple | None) -> bool:
    if layers is None:
        return True
    start, end = layers
    return start <= layer_index <= end


def _shape_mask(shape: dict, hw: tuple) -> np.ndarray:
    """Rasterize a shape (pixel coords) to a boolean (height, width) mask."""
    height, width = hw
    canvas = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    kind = shape["type"]
    if kind == "rect":
        x, y, w, h = shape["x"], shape["y"], shape["w"], shape["h"]
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=1)
    elif kind == "circle":
        cx, cy, r = shape["cx"], shape["cy"], shape["r"]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
    else:  # polygon (validated upstream)
        draw.polygon([tuple(point) for point in shape["points"]], fill=1)
    return np.array(canvas, dtype=bool)
