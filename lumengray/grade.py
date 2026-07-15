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


def apply_ramp(f: np.ndarray, stops, interp: str, band_px: int = 0) -> np.ndarray:
    """Map a normalized field ``f`` (0..1) to 8-bit exposure via (pos, value) stops —
    ``linear`` interpolates between them, ``step`` holds each stop's value until the
    next. Shared by the base gradient and the structure->core grade.

    ``band_px`` (``step`` only, and only for a 2-D field) lays a white crosslink wall
    this many voxels thick along every step boundary — a fully-cured seam welding
    adjacent bands together."""
    pos = np.array([s[0] for s in stops], dtype=np.float64)
    val = np.array([s[1] for s in stops], dtype=np.float64)
    if interp == "step":
        idx = np.clip(np.searchsorted(pos, f, side="right") - 1, 0, len(val) - 1)
        out = val[idx].astype(np.float64)
        if band_px > 0 and idx.ndim == 2:
            out = np.where(_step_seam_mask(idx, band_px), 255.0, out)
    else:
        out = np.interp(f, pos, val)  # clamps to the end values outside [pos0, posN]
    return np.round(out).astype(np.uint8)


def _step_seam_mask(idx: np.ndarray, band_px: int) -> np.ndarray:
    """White-band mask at each step boundary: the 1-voxel line on the higher side of
    every band transition (any direction), dilated to ``band_px`` voxels thick."""
    line = np.zeros(idx.shape, dtype=bool)
    line[1:, :] |= idx[1:, :] != idx[:-1, :]
    line[:, 1:] |= idx[:, 1:] != idx[:, :-1]
    if band_px > 1:
        line = ndimage.binary_dilation(line, iterations=int(band_px) - 1)
    return line


def _profile(f: np.ndarray, grade: Grade) -> np.ndarray:
    """Structure->core ramp: normalized distance-from-structure ``f`` (0 struts -> 1 core)."""
    return apply_ramp(f, grade.stops, grade.interp, grade.band_px)


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
