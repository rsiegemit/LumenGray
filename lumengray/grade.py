"""Structure->core exposure gradient for tessellation cells.

Grades a rendered tessellation layer by distance from the white struts inward:
white at the structure -> designed greys -> black at the cell core. The ramp's
speed (curve) and continuous-vs-piecewise (stepped) profile are designable. It's
a post-process (like the gyroid overlay), applied in ``render_layer``.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import Grade


def _profile(f: np.ndarray, grade: Grade) -> np.ndarray:
    """Map normalized distance-from-structure ``f`` (0 at struts -> 1 at core) to
    an 8-bit exposure: 255 at the struts down to 0 at the core, curved by ``speed``
    and optionally quantized into ``steps`` discrete levels (0 = continuous)."""
    base = np.clip(1.0 - f, 0.0, 1.0) ** grade.speed  # 1 at struts -> 0 at core
    if grade.steps >= 2:
        base = np.round(base * (grade.steps - 1)) / (grade.steps - 1)
    return np.round(base * 255.0).astype(np.uint8)


def grade_layer(layer: np.ndarray, solid: np.ndarray, grade: Grade, norm_px: float) -> np.ndarray:
    """Replace the non-white fill with a distance-from-structure grayscale ramp.
    White pixels (struts, rim, caps) are kept; everything else inside the solid is
    graded by its distance to the nearest white pixel, normalized by ``norm_px``
    (the cell inradius, so the deepest core reaches black)."""
    white = layer == 255
    if not white.any():
        return layer  # no structure to grade from
    d = ndimage.distance_transform_edt(~white)
    f = np.clip(d / max(1.0, norm_px), 0.0, 1.0)
    graded = _profile(f, grade)
    return np.where(solid & ~white, graded, layer)
