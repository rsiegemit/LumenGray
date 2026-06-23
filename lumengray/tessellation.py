"""Cubic-tessellation grayscale mode.

A 3D infill for the photostack: the model interior is filled with a lattice of
hollow cubes (white shell, grey core), each layer is wrapped in a pure-white
boundary rim, and the stack is capped top and bottom with solid-white layers.

Everything is reasoned about in *voxels*: one voxel is an output pixel in XY
and one photostack layer in Z. With the printer's 35um XY pixels and 50um
layers the voxels - and the cubes - are only approximately cubic, by design.

The lattice is anchored to the canvas (pixel column/row 0) in XY and to the
first interior layer in Z, so every layer is registered to the same 3D grid and
the cubes stack into true hollow boxes. Works on any sliced geometry: the solid
mask both clips the lattice and supplies the per-layer boundary edge.
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
    xy_pixel_um: float,
) -> np.ndarray:
    """Return the uint8 grayscale layer for one slice under cubic tessellation."""
    white = np.uint8(tess.white_value)
    layer = np.zeros(solid.shape, dtype=np.uint8)

    if _is_cap(layer_index, total_layers, tess):
        return np.where(solid, white, layer)

    shell = _shell_mask(solid.shape, layer_index, tess)
    layer = np.where(solid, np.where(shell, white, np.uint8(tess.grey_value)), layer)

    rim = _boundary_mask(solid, tess.boundary_um, xy_pixel_um)
    return np.where(rim, white, layer)


def _is_cap(layer_index: int, total_layers: int, tess: CubicTessellation) -> bool:
    return (
        layer_index <= tess.cap_bottom_layers
        or layer_index > total_layers - tess.cap_top_layers
    )


def _shell_mask(shape: tuple, layer_index: int, tess: CubicTessellation) -> np.ndarray:
    """Boolean (height, width): True where this layer's voxels are cube shell (white)."""
    height, width = shape
    # 0-based layer position within the tessellated (interior) region.
    z_in_cube = (layer_index - 1 - tess.cap_bottom_layers) % tess.cube_z_layers
    if _on_edge(z_in_cube, tess.cube_z_layers, tess.shell_px):
        # A top/bottom face of the cube row: the whole footprint is white.
        return np.ones(shape, dtype=bool)

    col_shell = _axis_shell(width, tess.cube_xy_px, tess.shell_px)
    row_shell = _axis_shell(height, tess.cube_xy_px, tess.shell_px)
    return col_shell[None, :] | row_shell[:, None]


def _axis_shell(length: int, cube: int, shell: int) -> np.ndarray:
    """Boolean along one axis: True where the voxel is within `shell` of a cube face."""
    position = np.arange(length) % cube
    return (position < shell) | (position >= cube - shell)


def _on_edge(position: int, cube: int, shell: int) -> bool:
    return position < shell or position >= cube - shell


def _boundary_mask(solid: np.ndarray, boundary_um: float, xy_pixel_um: float) -> np.ndarray:
    """Solid pixels within boundary_um (L-inf / chessboard) of the nearest edge."""
    boundary_px = max(1, round(boundary_um / xy_pixel_um))
    distance = ndimage.distance_transform_cdt(solid, metric="chessboard")
    return solid & (distance <= boundary_px)
