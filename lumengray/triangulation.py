"""Triangular (Buckminster-Fuller-style) tessellation — the triangular kind.

Reuses the shared tessellation base (caps, struts, Z frames, outer boundary rim
in tessellation._assemble); the only difference from cubic is the XY grid. Here
three families of parallel lines at 60 degrees tile the plane into equilateral
triangles, giving white vertical columns at the grid nodes braced by horizontal
triangular frames, with grey triangle faces/core.
"""

from __future__ import annotations

import numpy as np

from .config import TriangularTessellation
from .tessellation import _assemble

_SQRT3_2 = np.sqrt(3.0) / 2.0


def triangulation_layer(
    solid: np.ndarray,
    layer_index: int,  # 1-indexed
    total_layers: int,
    tri: TriangularTessellation,
) -> np.ndarray:
    """One slice under triangular tessellation: 3-family grid → columns + frames."""
    return _assemble(
        solid, layer_index, total_layers, tri, tri.z_layers,
        _make_xy_near(tri.tri_px), _make_xy_core(tri.tri_px),
    )


def tri_core_depth(shape, tri: TriangularTessellation) -> np.ndarray:
    """Inward-depth field for the structure->core gradient: 0 on the triangle's
    lines (the cell walls/struts) rising to 1 at the centroid (core), normalized by
    the triangle inradius. Layer-independent — the triangular grid is identical
    every layer — so the gradient flows cleanly inward per triangle instead of
    radiating from the sparse vertex columns of a single slice."""
    spacing = tri.tri_px * _SQRT3_2
    inradius = spacing / 3.0
    height, width = shape
    x = np.arange(width, dtype=np.float32)[None, :]
    y = np.arange(height, dtype=np.float32)[:, None]

    def dist_to_lines(p):
        m = np.mod(p, spacing)
        return np.minimum(m, spacing - m)

    md = dist_to_lines(y)
    md = np.minimum(md, dist_to_lines(-x * _SQRT3_2 + y * 0.5))
    md = np.minimum(md, dist_to_lines(-x * _SQRT3_2 - y * 0.5))
    return np.clip(md / inradius, 0.0, 1.0)


def _make_xy_core(tri_px: int):
    """Return xy_core(shape, core_px) → bool (h, w): the centre of each triangle.

    A pixel is in the core where it's far from every family's lines (near the cell
    centroid). The max such distance is the cell inradius (~spacing/3); the core is
    the region within ~core_px of that centroid.
    """
    spacing = tri_px * _SQRT3_2
    inradius = spacing / 3.0

    def _dist_to_lines(p):
        m = np.mod(p, spacing)
        return np.minimum(m, spacing - m)

    def xy_core(shape, core_px):
        height, width = shape
        x = np.arange(width, dtype=np.float32)[None, :]
        y = np.arange(height, dtype=np.float32)[:, None]
        md = _dist_to_lines(y)  # family 0 (horizontal)
        md = np.minimum(md, _dist_to_lines(-x * _SQRT3_2 + y * 0.5))
        md = np.minimum(md, _dist_to_lines(-x * _SQRT3_2 - y * 0.5))
        return md >= (inradius - core_px / 2.0)

    return xy_core


def _make_xy_near(tri_px: int):
    """Return an xy_near(shape, shell) → uint8 (h, w) count of triangular grid families."""
    spacing = tri_px * _SQRT3_2  # perpendicular distance between a family's parallel lines

    def xy_near(shape, shell):
        height, width = shape
        shell = float(shell)
        x = np.arange(width, dtype=np.float32)[None, :]
        y = np.arange(height, dtype=np.float32)[:, None]
        # Family 0: horizontal lines (depends on y only); families 1/2 at +/-60 deg.
        near = (np.mod(y[:, 0], spacing) < shell).astype(np.uint8)[:, None] * np.ones(width, np.uint8)
        p = -x * _SQRT3_2 + y * 0.5
        near = near + (np.mod(p, spacing) < shell)
        p = -x * _SQRT3_2 - y * 0.5
        near = near + (np.mod(p, spacing) < shell)
        return near

    return xy_near
