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
    """Map normalized distance-from-structure ``f`` (0 at struts -> 1 at core) to an
    8-bit exposure via the ramp's (pos, value) stops — ``linear`` interpolates
    between them, ``step`` holds each stop's value until the next."""
    pos = np.array([s[0] for s in grade.stops], dtype=np.float64)
    val = np.array([s[1] for s in grade.stops], dtype=np.float64)
    if grade.interp == "step":
        idx = np.clip(np.searchsorted(pos, f, side="right") - 1, 0, len(val) - 1)
        out = val[idx]
    else:
        out = np.interp(f, pos, val)  # clamps to the end values outside [pos0, posN]
    return np.round(out).astype(np.uint8)


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
