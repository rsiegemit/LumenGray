"""Cubic-tessellation grayscale mode.

A 3D infill for the photostack: the model interior is tiled with cubes whose
*edges* are white (vertical support columns + top/bottom frames) and whose faces
and core are grey. Each layer is wrapped in a pure-white boundary rim, and the
stack is capped top and bottom with solid-white layers.

Everything is reasoned about in *voxels*: one voxel is an output pixel in XY
and one photostack layer in Z. With the printer's 35um XY pixels and 50um
layers the voxels - and the cubes - are only approximately cubic, by design.

The lattice is anchored to the canvas (pixel column/row 0) in XY and to the
first interior layer in Z, so every layer is registered to the same 3D grid and
the struts stack into continuous columns. Works on any sliced geometry: the
solid mask both clips the lattice and supplies the per-layer boundary edge.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import CubicTessellation


def tessellation_layer(
    solid: np.ndarray,
    layer_index: int,  # 1-indexed
    total_layers: int,
    tess: CubicTessellation,
) -> np.ndarray:
    """Return the uint8 grayscale layer for one slice under cubic tessellation."""
    white = np.uint8(tess.white_value)
    layer = np.zeros(solid.shape, dtype=np.uint8)

    if _is_cap(layer_index, total_layers, tess):
        return np.where(solid, white, layer)

    strut = _strut_mask(solid.shape, layer_index, tess)
    layer = np.where(solid, np.where(strut, white, np.uint8(tess.grey_value)), layer)

    rim = _boundary_mask(solid, tess.boundary_px)
    return np.where(rim, white, layer)


def _is_cap(layer_index: int, total_layers: int, tess: CubicTessellation) -> bool:
    return (
        layer_index <= tess.cap_bottom_layers
        or layer_index > total_layers - tess.cap_top_layers
    )


def _strut_mask(shape: tuple, layer_index: int, tess: CubicTessellation) -> np.ndarray:
    """Boolean (height, width): True on the cube *edges* (white support struts).

    Struts live on a single shared grid — one `shell_px`-thick line per cube
    period (at the low face of each cell) — so adjacent cubes share a boundary
    instead of each drawing their own (which doubled the wall/frame thickness at
    every junction). A voxel is white where it lands on that grid line on at least
    TWO of the three axes: an interior layer shows vertical columns at the grid
    nodes, and a grid layer in Z shows an open frame.
    """
    height, width = shape
    # 0-based layer position within the tessellated (interior) region.
    z_in_cube = (layer_index - 1 - tess.cap_bottom_layers) % tess.cube_z_layers
    near_z = 1 if z_in_cube < tess.shell_px else 0  # shared frame at the cube boundary

    col_near = _axis_grid(width, tess.cube_xy_px, tess.shell_px)
    row_near = _axis_grid(height, tess.cube_xy_px, tess.shell_px)
    near_count = col_near[None, :].astype(np.uint8) + row_near[:, None].astype(np.uint8) + near_z
    return near_count >= 2


def _axis_grid(length: int, cube: int, shell: int) -> np.ndarray:
    """Boolean along one axis: True on the shared grid line (low `shell` of each period)."""
    return (np.arange(length) % cube) < shell


def _boundary_mask(solid: np.ndarray, boundary_px: int) -> np.ndarray:
    """Solid pixels within `boundary_px` (L-inf / chessboard) of the nearest edge."""
    if boundary_px <= 0:
        return np.zeros(solid.shape, dtype=bool)
    distance = ndimage.distance_transform_cdt(solid, metric="chessboard")
    return solid & (distance <= boundary_px)
