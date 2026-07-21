"""Minimum-feature enforcement ("grow-to-min") — the calibration guardrail FIX.

Grows cured features thinner than ``min_pillar`` and widens voids narrower than
``min_channel`` so they actually print. This is the one calibration operation that
MUTATES the exported photostack, so it is:

  * pure and isolated (numpy/scipy only — no config, no I/O), so it can be tested
    on its own;
  * strictly opt-in per category (``fix_pillar`` / ``fix_channel``);
  * a guaranteed BYTE-FOR-BYTE no-op when nothing is enabled or nothing is thin —
    it returns the *same array object* in that case.

Growing is deliberately toward "bigger prints reliably": a thin feature is dilated
outward until it clears the minimum (may slightly overshoot — the safe direction).
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def _disk(r: int) -> np.ndarray:
    r = int(r)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r * r


def thin_mask(mask: np.ndarray, r: int) -> np.ndarray:
    """Pixels of ``mask`` that belong to features THINNER than 2*r — corner-safe.

    Plain opening flags the rounded corners of *thick* regions as thin; dilating the
    opened (thick-core) image back by r re-covers those corners, so what remains is
    only genuinely thin structure (verified: a solid block yields zero)."""
    d = _disk(r)
    opened = ndimage.binary_opening(mask, structure=d)
    return mask & ~ndimage.binary_dilation(opened, structure=d)


def apply_min_feature(
    layer: np.ndarray,
    solid: np.ndarray,
    min_pillar_px: float = 0.0,
    min_channel_px: float = 0.0,
    fix_pillar: bool = False,
    fix_channel: bool = False,
    void_below: int = 64,
) -> np.ndarray:
    """Return a grow-to-min-corrected copy of ``layer`` (uint8), or ``layer`` itself
    (same object) if nothing was changed. ``solid`` is the part silhouette."""
    out = layer
    changed = False

    if fix_pillar and min_pillar_px >= 2:
        r = max(1, int(min_pillar_px) // 2)
        cured = out > 0
        thin = thin_mask(cured, r)
        if thin.any():
            grow = ndimage.binary_dilation(thin, structure=_disk(r)) & ~cured
            if grow.any():
                # New pixels take the local cured value (grey-dilate spreads exposure
                # outward), so a white strut thickens white, a grey one grey.
                spread = ndimage.grey_dilation(out, footprint=_disk(r))
                out = np.where(grow, spread, out).astype(np.uint8)
                changed = True

    if fix_channel and min_channel_px >= 2:
        r = max(1, int(min_channel_px) // 2)
        void = solid & (out < void_below)
        thin = thin_mask(void, r)
        if thin.any():
            grow = ndimage.binary_dilation(thin, structure=_disk(r)) & solid
            if grow.any():
                out = np.where(grow, np.uint8(0), out).astype(np.uint8)
                changed = True

    return out if changed else layer
