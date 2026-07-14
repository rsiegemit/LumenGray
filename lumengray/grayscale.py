"""Build grayscale layers from binary masks.

Replaces protocol step 3 (ImageJ select + fill). A base fill (flat value or a
geometry-driven gradient) is computed for cured pixels, then config regions are
rasterized and overlaid on top.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .config import Gradient
from .grade import apply_ramp


def base_layer(
    solid: np.ndarray,
    gradient: Gradient | None,
    default_solid_value: int,
    layer_index: int = 1,
    total_layers: int = 1,
) -> np.ndarray:
    """Return the uint8 base fill for cured pixels (background stays 0). With a
    ``gradient``, map its normalized radial/linear field through the ramp graph."""
    if gradient is None:
        return np.where(solid, np.uint8(default_solid_value), 0).astype(np.uint8)
    field = _gradient_field(solid, gradient, layer_index, total_layers)
    values = apply_ramp(field, gradient.stops, gradient.interp)
    return np.where(solid, values, 0).astype(np.uint8)


def _gradient_field(solid: np.ndarray, gradient: Gradient, layer_index: int, total_layers: int) -> np.ndarray:
    """Normalized [0,1] field: radial = 0 at the part's XY centre -> 1 at its farthest
    pixel; linear x/y = across the footprint (0 at one end -> 1 at the other); linear
    z = this layer's fraction up the stack. Normalized to the part so 0 and 1 land on
    the actual extremes."""
    height, width = solid.shape
    if gradient.mode == "linear" and gradient.axis == "z":
        frac = 0.0 if total_layers <= 1 else (layer_index - 1) / (total_layers - 1)
        return np.full(solid.shape, frac, dtype=np.float64)
    ys, xs = np.where(solid)
    if xs.size == 0:
        return np.zeros(solid.shape, dtype=np.float64)
    if gradient.mode == "linear":
        if gradient.axis == "x":
            lo, hi = int(xs.min()), int(xs.max())
            coord = np.broadcast_to(np.arange(width, dtype=np.float64), solid.shape)
        else:  # "y"
            lo, hi = int(ys.min()), int(ys.max())
            coord = np.broadcast_to(np.arange(height, dtype=np.float64)[:, None], solid.shape)
        return np.clip((coord - lo) / max(1.0, hi - lo), 0.0, 1.0)
    # radial: distance from the footprint's bbox centre, normalized by the farthest solid pixel
    cx = (int(xs.min()) + int(xs.max())) / 2.0
    cy = (int(ys.min()) + int(ys.max())) / 2.0
    gy, gx = np.mgrid[0:height, 0:width].astype(np.float64)
    dist = np.hypot(gx - cx, gy - cy)
    dmax = float(dist[solid].max()) or 1.0
    return np.clip(dist / dmax, 0.0, 1.0)


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
