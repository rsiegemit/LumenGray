"""Gyroid void-connector overlay.

Carves a continuous triply-periodic minimal surface (gyroid) void through an
already-rendered layer, threading isolated black (lumen) regions into one
interconnected, drainable perfusion network. Composes on top of ANY grayscale
mode — it's a post-process, not an infill of its own.

The gyroid is the closed-form field
    G(x,y,z) = sin(ax)cos(ay) + sin(ay)cos(az) + sin(az)cos(ax),  a = 2*pi / cell.
The thin band |G| < t around its zero level-set is a single, space-filling,
fully-connected surface, so carving it to void (0) links every region it threads
through and drains to the part's outer surface. Evaluated in MILLIMETRE space so
the network stays isotropic despite the anisotropic 35um-XY / 50um-Z voxels.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import GyroidChannel, Printer


def gyroid_carve(layer: np.ndarray, solid: np.ndarray, layer_index: int, printer: Printer, g: GyroidChannel) -> np.ndarray:
    """Return ``layer`` with a gyroid-surface void carved through the solid."""
    width_mm = printer.voxel_width_um / 1000.0
    length_mm = printer.voxel_length_um / 1000.0
    layer_mm = printer.voxel_height_um / 1000.0
    height, width = layer.shape
    a = 2.0 * np.pi / g.cell_mm
    z = (layer_index - 0.5) * layer_mm  # this layer's height in mm

    x = (np.arange(width, dtype=np.float32) * width_mm)[None, :]
    y = (np.arange(height, dtype=np.float32) * length_mm)[:, None]
    sax, cax = np.sin(a * x), np.cos(a * x)
    say, cay = np.sin(a * y), np.cos(a * y)
    sz, cz = np.sin(a * z), np.cos(a * z)
    field = sax * cay + say * cz + sz * cax

    # Distance to the gyroid surface ≈ |G| / |grad G| (grad computed analytically),
    # so the carved channel is a consistent channel_px voxels wide everywhere and
    # rasterizes to whole voxels (our minimum unit) — not a variable-width band.
    gx = cax * cay - sz * sax
    gy = -sax * say + cay * cz
    gz = -say * sz + cz * cax
    grad = np.sqrt(gx * gx + gy * gy + gz * gz) + 1e-6  # = |grad G| / a
    channel = np.abs(field) < a * (g.channel_px * width_mm / 2.0) * grad

    # Keep a solid skin: only carve where the pixel is >= skin_px inside the part
    # surface, so the void never breaches the boundary (or any internal hole edge).
    interior = solid
    if g.skin_px > 0:
        interior = ndimage.distance_transform_edt(solid) > g.skin_px
    return np.where(interior & channel, np.uint8(0), layer)
