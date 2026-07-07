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


def distance_depth(layer: np.ndarray, norm_px: float) -> np.ndarray | None:
    """Generic inward-depth field for axis-aligned lattices (cubic): distance to
    the nearest white strut, normalized by the cell inradius ``norm_px`` (0 at the
    struts -> ~1 at the cell core). Returns None if there are no struts to grade."""
    white = layer == 255
    if not white.any():
        return None
    d = ndimage.distance_transform_edt(~white)
    return np.clip(d / max(1.0, norm_px), 0.0, 1.0)


def grade_layer(layer: np.ndarray, solid: np.ndarray, grade: Grade, depth: np.ndarray | None) -> np.ndarray:
    """Replace the non-white fill with the ramp applied to a per-cell inward
    ``depth`` field (0 at the struts -> 1 at the core). White pixels (struts, rim,
    caps) are kept. ``depth`` is mode-specific so each element grades cleanly inward
    (see the tessellation modules); None leaves the layer unchanged."""
    if depth is None:
        return layer
    graded = _profile(np.clip(depth, 0.0, 1.0), grade)
    return np.where(solid & (layer != 255), graded, layer)
