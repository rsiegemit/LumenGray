"""Tessellation grayscale modes — shared base + the cubic kind.

A tessellation infill tiles the model interior with a strut lattice: white
support struts (columns at the grid nodes, braced by horizontal frames every
`z_period` layers), grey faces/core, solid-white caps top and bottom, and a
white boundary rim on the part's outer wall. The only thing that differs between
*kinds* is the XY grid — how many grid-line families a pixel lands on:

  - cubic     → a square grid (2 families: columns + rows)
  - triangular→ a 60-degree triangular grid (3 families)   [see triangulation.py]

`_assemble` holds all the shared scaffolding; each kind supplies a callable that
returns the per-pixel XY family count. Everything is reasoned about in voxels:
one voxel is an output pixel in XY and one photostack layer in Z.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import CubicTessellation


def _assemble(solid, layer_index, total_layers, params, z_period, xy_near_count, xy_core):
    """Shared per-layer build for any tessellation kind.

    `params` provides the common fields (caps, shell_px, core_px, boundary_px,
    grey/white). `z_period` is the kind's Z frame spacing. `xy_near_count(shape,
    shell)` returns a uint8 (h, w) count of XY grid-line families each pixel is on
    (>= 2 counting the Z frame → white strut). `xy_core(shape, core_px)` returns a
    bool (h, w) of each cell's centre region (carved to black/void in the middle
    layers of the cell).
    """
    white = np.uint8(params.white_value)
    layer = np.zeros(solid.shape, dtype=np.uint8)

    if layer_index <= params.cap_bottom_layers or layer_index > total_layers - params.cap_top_layers:
        return np.where(solid, white, layer)  # solid-white cap

    z_in = (layer_index - 1 - params.cap_bottom_layers) % z_period
    near_z = 1 if z_in < params.shell_px else 0  # shared horizontal frame at the low side
    near = xy_near_count(solid.shape, params.shell_px)
    strut = (near + near_z) >= 2

    layer = np.where(solid, np.where(strut, white, np.uint8(params.grey_value)), layer)

    # Black (void) core centred in each cell — only the cell's middle Z layers.
    core_px = params.core_px
    if core_px > 0:
        z_lo = (z_period + params.shell_px - core_px) // 2  # centre between Z frames (frame sits at low shell)
        if z_lo <= z_in < z_lo + core_px:
            layer = np.where(solid & xy_core(solid.shape, core_px), np.uint8(0), layer)

    rim = _boundary_mask(solid, params.boundary_px)
    return np.where(rim, white, layer)


# ── Cubic kind ───────────────────────────────────────────
def tessellation_layer(
    solid: np.ndarray,
    layer_index: int,  # 1-indexed
    total_layers: int,
    tess: CubicTessellation,
) -> np.ndarray:
    """One slice under cubic tessellation: square grid → columns + frames."""
    def xy_near(shape, shell):
        height, width = shape
        col = _axis_grid(width, tess.cube_xy_px, shell)
        row = _axis_grid(height, tess.cube_xy_px, shell)
        return col[None, :].astype(np.uint8) + row[:, None].astype(np.uint8)

    def xy_core(shape, core):
        height, width = shape
        col = _axis_center(width, tess.cube_xy_px, core, tess.shell_px)
        row = _axis_center(height, tess.cube_xy_px, core, tess.shell_px)
        return col[None, :] & row[:, None]

    return _assemble(solid, layer_index, total_layers, tess, tess.cube_z_layers, xy_near, xy_core)


def _axis_grid(length: int, period: int, shell: int) -> np.ndarray:
    """Boolean along one axis: True on the shared grid line (low `shell` of each period)."""
    return (np.arange(length) % period) < shell


def _axis_center(length: int, period: int, core: int, shell: int = 0) -> np.ndarray:
    """Boolean along one axis: True on the central `core` band of each cell.
    The strut wall occupies the low `shell` px of each period, so the cell centre
    sits at (period + shell) / 2 — offset the band by `shell` to keep the core
    centred between the walls rather than pulled toward the low-side strut."""
    pos = np.arange(length) % period
    lo = (period + shell - core) // 2
    return (pos >= lo) & (pos < lo + core)


# ── Shared boundary rim ──────────────────────────────────
# How wide a void (px) still counts as an internal channel to skip for the rim.
# Closing bridges gaps up to ~2x this, so ~3.4 mm at 35 um pixels.
_CHANNEL_BRIDGE_PX = 48


def _boundary_mask(solid: np.ndarray, boundary_px: int) -> np.ndarray:
    """Solid pixels within `boundary_px` of the part's OUTER wall (L-inf).

    The rim tracks the outer silhouette only: enclosed holes are filled and thin
    internal channels are bridged, so pixels next to a drilled channel stay grey
    (no boundary) while the model's outer skin still gets its white rim.

    Computed PER connected part: each separate body (e.g. a batch of copies, which
    the channel-bridging closing would otherwise fuse into one blob) gets its own
    complete wall on every side, not just the array's outer perimeter.
    """
    if boundary_px <= 0:
        return np.zeros(solid.shape, dtype=bool)
    rim = np.zeros(solid.shape, dtype=bool)
    labels, n = ndimage.label(solid)
    if n == 0:
        return rim
    for sl, comp_id in zip(ndimage.find_objects(labels), range(1, n + 1)):
        comp = labels[sl] == comp_id  # this body alone (other bodies in the box are excluded)
        rim[sl] |= _component_rim(comp, boundary_px)
    return rim


def _component_rim(comp: np.ndarray, boundary_px: int) -> np.ndarray:
    """The outer-wall rim of ONE connected body (True = solid), within its own box."""
    pad = _CHANNEL_BRIDGE_PX + 2
    padded = np.pad(comp, pad)
    # Outer silhouette: close thin channels, then fill any fully enclosed holes.
    outer = ndimage.binary_closing(padded, iterations=_CHANNEL_BRIDGE_PX, border_value=0)
    outer = ndimage.binary_fill_holes(outer)
    distance = ndimage.distance_transform_cdt(outer, metric="chessboard")[pad:-pad, pad:-pad]
    return comp & (distance <= boundary_px)
