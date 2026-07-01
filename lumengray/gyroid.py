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

from .config import GyroidChannel, Printer


def gyroid_carve(layer: np.ndarray, solid: np.ndarray, layer_index: int, printer: Printer, g: GyroidChannel) -> np.ndarray:
    """Return ``layer`` with a gyroid-surface void carved through the solid."""
    pixel_mm = printer.pixel_size_um / 1000.0
    layer_mm = printer.layer_height_um / 1000.0
    height, width = layer.shape
    a = 2.0 * np.pi / g.cell_mm
    z = (layer_index - 0.5) * layer_mm  # this layer's height in mm

    x = (np.arange(width, dtype=np.float32) * pixel_mm)[None, :]
    y = (np.arange(height, dtype=np.float32) * pixel_mm)[:, None]
    sz, cz = np.sin(a * z), np.cos(a * z)
    field = np.sin(a * x) * np.cos(a * y) + np.sin(a * y) * cz + sz * np.cos(a * x)

    # |G| < t is a band of half-width ~ t/|grad G| about the surface; |grad G| ~ a,
    # so a channel of half-width (channel_px/2) voxels → t = a * (channel_px/2 * pixel_mm).
    t = a * (g.channel_px * pixel_mm / 2.0)
    channel = np.abs(field) < t
    return np.where(solid & channel, np.uint8(0), layer)
