"""Wireframe (outline-only) grayscale mode.

Draws each layer's cross-section *perimeter* (and any hole edges) at a chosen
exposure, leaving the rest as the complementary fill. Stacked over the layers
this prints the model's outline/shell rather than a solid body.

  white → white outline (255) on void (0)
  gray  → grey outline (128) on void (0)
  black → void outline (0) grooved into a solid white body (255)  [inverse]
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import Wireframe

# color → (outline value, interior fill value)
_COLORS = {"white": (255, 0), "gray": (128, 0), "black": (0, 255)}


def wireframe_layer(solid: np.ndarray, wf: Wireframe) -> np.ndarray:
    """Return the uint8 grayscale layer for one slice under wireframe mode."""
    line_value, fill_value = _COLORS[wf.color]
    layer = np.where(solid, np.uint8(fill_value), np.uint8(0))
    if wf.line_px > 0:
        distance = ndimage.distance_transform_cdt(solid, metric="chessboard")
        outline = solid & (distance <= wf.line_px)
        layer = np.where(outline, np.uint8(line_value), layer)
    return layer
