"""Procedural calibration-chip photostack generator.

Unlike the STL pipeline, the calibration chip is drawn DIRECTLY as grayscale layers
— because the whole point is controlling the exposure (gray value) of each zone,
which a mesh can't carry. One flat chip fills the build area.

CRITICAL — the LumenX prints HYDROGEL. Thin lines, tick marks and text do NOT
survive as gel, so the PRINTED layers contain only robust, printable gel features:
solid patches, pillars, gaps, thick comb teeth and frames. All human-readable labels
(zone names, ruler numbers, gray values, feature sizes) live ONLY in a separate
labeled *reference map* — an on-screen / exported guide that is never printed. The
``answer_key`` + ``measurement.csv`` map each zone's POSITION to its nominal value.

Zones (all measured under microscope / calipers):
  * X/Y comb scale bars   -> true pixel pitch + anisotropy (thick teeth at 5 mm)
  * nested square frames   -> is the scale error size-dependent?
  * grayscale step wedge   -> which grays cure, and how (0..255 patches)
  * gray x feature matrix  -> lateral growth/shrink per gray (pillars + holes)
  * resolution grating      -> smallest resolvable line pairs
  * outer frame + L-ruler   -> measurement datum + rotation/squareness + orientation

Everything is reasoned about in voxels (one output pixel in XY, one layer in Z). The
chip is a solid-white raft (``base_layers``) with the pattern extruded on top
(``feature_layers``); the pattern is identical every feature layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WHITE = 255
LABEL = (100, 181, 255)      # reference-map annotation colour (never printed)
LABEL_DIM = (120, 130, 150)


@dataclass(frozen=True)
class CalibrationSpec:
    width_px: int
    height_px: int
    voxel_width_um: float          # X pitch
    voxel_length_um: float         # Y pitch
    voxel_height_um: float         # Z layer
    margin_px: int = 24            # blank border kept clear of the build-area edge
    base_layers: int = 8           # solid-white raft under everything
    feature_layers: int = 16       # extruded pattern height
    wedge_steps: int = 16          # patches across the 0..255 grayscale step wedge
    matrix_grays: tuple = (255, 208, 160, 112, 64, 32)      # rows of the gray x feature matrix
    feature_widths_px: tuple = (1, 2, 3, 4, 6, 8, 12)       # columns (line/pillar widths, px)
    block_mm: tuple = (2.0, 5.0, 10.0, 15.0)               # nested square frames
    variant: str = "full"          # "full" (whole build area) | "small" (a 1 cm chip)
    chip_mm: float = 10.0          # small variant: chip side length (XY)
    chip_height_mm: float = 0.0    # small variant: feature height in mm (0 = use feature_layers)
    pyramid_grid: int = 2          # small variant: N x N pyramids per quadrant (base sizes sweep)
    checker_min: int = 64          # small variant: low end of the grayscale-checker range
    checker_max: int = 255         # small variant: high end of the grayscale-checker range
    channel_count: int = 4         # small variant: number of open channels (trenches)
    channel_max_px: int = 8        # small variant: widest channel (widths sweep 1..this)
    material: str = ""
    exposure: str = ""
    note: str = ""


def build_spec(raw: dict, printer) -> CalibrationSpec:
    raw = raw or {}
    def _i(k, d):
        try:
            return max(0, int(raw.get(k, d)))
        except (TypeError, ValueError):
            return d
    voxel_height_um = float(printer.voxel_height_um)
    feature_layers = max(1, _i("feature_layers", 16))
    chip_height_mm = max(0.0, float(raw.get("chip_height_mm", 0.0) or 0.0))
    if chip_height_mm > 0:  # physical height overrides the raw feature-layer count
        feature_layers = max(1, round(chip_height_mm * 1000.0 / voxel_height_um))
    return CalibrationSpec(
        width_px=int(printer.resolution[0]),
        height_px=int(printer.resolution[1]),
        voxel_width_um=float(printer.voxel_width_um),
        voxel_length_um=float(printer.voxel_length_um),
        voxel_height_um=voxel_height_um,
        margin_px=_i("margin_px", 24),
        base_layers=max(1, _i("base_layers", 8)),
        feature_layers=feature_layers,
        wedge_steps=max(2, _i("wedge_steps", 16)),
        variant=("small" if str(raw.get("variant", "full")) == "small" else "full"),
        chip_mm=max(2.0, float(raw.get("chip_mm", 10.0) or 10.0)),
        chip_height_mm=chip_height_mm,
        pyramid_grid=max(1, min(6, _i("pyramid_grid", 2))),
        checker_min=max(0, min(255, _i("checker_min", 64))),
        checker_max=max(0, min(255, _i("checker_max", 255))),
        channel_count=max(1, min(16, _i("channel_count", 4))),
        channel_max_px=max(1, _i("channel_max_px", 8)),
        material=str(raw.get("material", "") or ""),
        exposure=str(raw.get("exposure", "") or ""),
        note=str(raw.get("note", "") or ""),
    )


def total_layers(spec: CalibrationSpec) -> int:
    return spec.base_layers + spec.feature_layers


_CACHE: dict = {}


def _cached(key, builder):
    if key not in _CACHE:
        if len(_CACHE) >= 8:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = builder()
    return _CACHE[key]


def render_calibration_layer(spec: CalibrationSpec, index: int) -> np.ndarray:
    """One 1-indexed PRINTED layer (uint8, gel-only). Raft = solid-white chip; feature
    layers = the gel pattern (extruded for the full chip; genuinely 3D — pyramids,
    buried channels — for the small chip, so it varies with the layer)."""
    if spec.variant == "small":
        return _small_layer(spec, index)
    if index <= spec.base_layers:
        img = np.zeros((spec.height_px, spec.width_px), dtype=np.uint8)
        m = spec.margin_px
        img[m:spec.height_px - m, m:spec.width_px - m] = WHITE
        return img
    return _cached(("gel", repr(spec)), lambda: _gel_features(spec))


def render_reference(spec: CalibrationSpec) -> np.ndarray:
    """A LABELED reference map (RGB) for interpretation — the gel features in grey with
    zone names / values overlaid in colour. NEVER printed; this is your measurement guide."""
    if spec.variant == "small":
        return _cached(("sref", repr(spec)), lambda: _small_reference(spec))
    return _cached(("ref", repr(spec)), lambda: _reference_image(spec))


# ── layout ───────────────────────────────────────────────

def _layout(spec: CalibrationSpec) -> dict:
    W, H, m = spec.width_px, spec.height_px, spec.margin_px
    inner = (m + 16, m + 16, W - m - 16, H - m - 16)
    ruler_h = 74
    ax0, ay0, ax1, ay1 = inner[0] + ruler_h + 12, inner[1] + ruler_h + 12, inner[2], inner[3]
    right_w = 500
    rx0 = ax1 - right_w
    rsplit = ay0 + int((ay1 - ay0) * 0.62)
    lx1 = rx0 - 14
    row_split = ay0 + int((ay1 - ay0) * 0.42)
    title_w = 330
    return {
        "inner": inner, "ruler_h": ruler_h,
        "x_ruler": (inner[0] + ruler_h, inner[1], inner[2], inner[1] + ruler_h),
        "y_ruler": (inner[0], inner[1] + ruler_h, inner[0] + ruler_h, inner[3]),
        "title": (ax0, ay0, ax0 + title_w, row_split),
        "wedge": (ax0 + title_w + 12, ay0, lx1, row_split),
        "matrix": (ax0, row_split + 12, lx1, ay1),
        "squares": (rx0, ay0, ax1, rsplit),
        "grating": (rx0, rsplit + 12, ax1, ay1),
    }


# ── printed gel features (no text) ───────────────────────

def _gel_features(spec: CalibrationSpec) -> np.ndarray:
    W, H, m = spec.width_px, spec.height_px, spec.margin_px
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    lay = _layout(spec)
    # outer frame rim (a thick printable gel border + known outer rectangle)
    d.rectangle([m, m, W - m - 1, H - m - 1], outline=WHITE, width=8)
    _comb(d, lay["x_ruler"], spec.voxel_width_um / 1000.0, horizontal=True)
    _comb(d, lay["y_ruler"], spec.voxel_length_um / 1000.0, horizontal=False)
    _squares(d, lay["squares"], spec)
    _wedge(d, lay["wedge"], spec)
    _matrix(d, lay["matrix"], spec)
    _grating(d, lay["grating"], spec)
    return np.array(img, dtype=np.uint8)


def _reference_image(spec: CalibrationSpec) -> np.ndarray:
    gel = _gel_features(spec)
    rgb = Image.fromarray(np.stack([gel // 2 + 40, gel // 2 + 40, gel // 2 + 40], axis=-1), "RGB")
    d = ImageDraw.Draw(rgb)
    _annotate(d, spec, _layout(spec))
    return np.array(rgb, dtype=np.uint8)


def _comb(d, rect, pitch_mm, horizontal):
    """Scale reference: a SOLID continuous gel bar (the robust end-to-end length datum
    — a single stroke of gel, nothing to wash away) with teeth every 5 mm on it for
    graduation. Measure the bar span for the true pixel pitch; the teeth check
    linearity mid-span."""
    x0, y0, x1, y1 = rect
    length = (x1 - x0) if horizontal else (y1 - y0)
    span_mm = int(length * pitch_mm)
    thick = (y1 - y0) if horizontal else (x1 - x0)
    base = 16  # solid baseline bar thickness
    if horizontal:
        d.rectangle([x0, y1 - base, x1, y1], fill=WHITE)          # continuous baseline
    else:
        d.rectangle([x1 - base, y0, x1, y1], fill=WHITE)
    for mm in range(0, span_mm + 1, 5):
        p = int(round(mm / pitch_mm))
        major = (mm % 10 == 0)
        tlen = thick * (0.8 if major else 0.55)
        tw = 10 if major else 7
        if horizontal:
            gx = x0 + p
            d.rectangle([gx - tw // 2, y1 - tlen, gx + tw // 2, y1], fill=WHITE)
        else:
            gy = y0 + p
            d.rectangle([x1 - tlen, gy - tw // 2, x1, gy + tw // 2], fill=WHITE)


def _squares(d, rect, spec):
    """Nested square FRAMES (thick, printable) sharing the bottom-left corner + a small
    solid block. Measure each edge for scale + size-dependence."""
    x0, y0, x1, y1 = _inner(rect)
    px_mm = spec.voxel_width_um / 1000.0
    py_mm = spec.voxel_length_um / 1000.0
    ox, oy = x0 + 6, y1 - 6
    for mm in sorted(spec.block_mm, reverse=True):
        w = int(round(mm / px_mm)); h = int(round(mm / py_mm))
        if ox + w > x1 or oy - h < y0:
            continue
        d.rectangle([ox, oy - h, ox + w, oy], outline=WHITE, width=6)
    smallest = min(spec.block_mm)
    sw = int(round(smallest / px_mm)); sh = int(round(smallest / py_mm))
    d.rectangle([ox, oy - sh, ox + sw, oy], fill=WHITE)


def _wedge(d, rect, spec):
    x0, y0, x1, y1 = _inner(rect)
    n = spec.wedge_steps
    cw = (x1 - x0) / n
    for i in range(n):
        g = round(i * 255 / (n - 1))
        d.rectangle([x0 + i * cw + 2, y0, x0 + (i + 1) * cw - 2, y1 - 22], fill=g)


def _matrix(d, rect, spec):
    x0, y0, x1, y1 = _inner(rect)
    grays, widths = spec.matrix_grays, spec.feature_widths_px
    rows = len(grays)
    row_h = (y1 - y0) / rows
    half = (x1 - x0 - 42) // 2
    pos_x0 = x0 + 42
    neg_x0 = pos_x0 + half + 12
    cell_w = half / len(widths)
    tile = min(cell_w, row_h) * 0.62
    for i, g in enumerate(grays):
        cy = y0 + i * row_h + row_h / 2 + 8
        for j, wpx in enumerate(widths):
            # positive PILLAR: a solid dot of diameter wpx at gray g on the void field.
            # Measure whether it prints and how much it grows (over-exposure) with dose.
            px = pos_x0 + j * cell_w + cell_w / 2
            _dot(d, px, cy, wpx, int(g))
            # negative HOLE: a solid gray-g tile (material at this exposure) with a round
            # void of diameter wpx cut in — measure how the hole closes with dose.
            nx = neg_x0 + j * cell_w + cell_w / 2
            d.rectangle([nx - tile / 2, cy - tile / 2, nx + tile / 2, cy + tile / 2], fill=int(g))
            _dot(d, nx, cy, wpx, 0)


def _dot(d, cx, cy, diam, fill):
    r = max(0.5, diam / 2.0)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _grating(d, rect, spec):
    x0, y0, x1, y1 = _inner(rect)
    y = y0
    for wpx in spec.feature_widths_px:
        band_h = 22
        if y + band_h > y1:
            break
        gx = x0 + 58
        while gx + wpx <= x1:
            d.rectangle([gx, y, gx + wpx - 1, y + band_h - 1], fill=WHITE)
            gx += 2 * wpx
        y += band_h + 8


# ── reference-map labels (never printed) ─────────────────

def _annotate(d, spec, lay):
    f_sm, f_md = _font(15), _font(20)
    px_mm = spec.voxel_width_um / 1000.0
    py_mm = spec.voxel_length_um / 1000.0

    _ruler_labels(d, lay["x_ruler"], px_mm, "X ruler (mm)", f_sm, horizontal=True)
    _ruler_labels(d, lay["y_ruler"], py_mm, "Y (mm)", f_sm, horizontal=False)

    # zone titles + a "not printed" note
    _label(d, lay["title"], "TITLE / NOTES (reference only)", f_md)
    tx, ty, _, _ = _inner(lay["title"])
    for k, ln in enumerate([
        f"px {spec.voxel_width_um:g}x{spec.voxel_length_um:g}um  z {spec.voxel_height_um:g}um",
        f"canvas {spec.width_px}x{spec.height_px}  layers {spec.base_layers}+{spec.feature_layers}",
        f"material: {spec.material or '—'}",
        f"exposure: {spec.exposure or '—'}",
        "PRINTED = gel features only.",
        "Labels here are NOT printed.",
    ]):
        d.text((tx, ty + k * (f_sm.size + 6)), ln, fill=LABEL, font=f_sm)

    _label(d, lay["wedge"], "GRAYSCALE STEP WEDGE (0->255)", f_md)
    wx0, wy0, wx1, wy1 = _inner(lay["wedge"])
    n = spec.wedge_steps
    cw = (wx1 - wx0) / n
    for i in (0, n // 2, n - 1):
        g = round(i * 255 / (n - 1))
        d.text((wx0 + i * cw + 2, wy1 - 20), str(g), fill=LABEL, font=f_sm)

    _label(d, lay["matrix"], "GRAY x FEATURE MATRIX  (left pillars +   right holes -)", f_md)
    _matrix_labels(d, lay["matrix"], spec, f_sm)

    _label(d, lay["squares"], "NESTED SQUARES (mm)", f_md)
    _squares_labels(d, lay["squares"], spec, f_sm)

    _label(d, lay["grating"], "RESOLUTION (line pairs)", f_md)
    gx0, gy0, gx1, gy1 = _inner(lay["grating"])
    y = gy0
    for wpx in spec.feature_widths_px:
        if y + 22 > gy1:
            break
        d.text((gx0, y + 3), f"{round(wpx * spec.voxel_width_um)}um", fill=LABEL, font=f_sm)
        y += 30


def _ruler_labels(d, rect, pitch_mm, title, font, horizontal):
    x0, y0, x1, y1 = rect
    d.text((x0 + 4, y0 + 2), title, fill=LABEL, font=font)
    span = int(((x1 - x0) if horizontal else (y1 - y0)) * pitch_mm)
    for mm in range(0, span + 1, 10):
        p = int(round(mm / pitch_mm))
        if horizontal:
            d.text((x0 + p + 2, y0 + 20), str(mm), fill=LABEL, font=font)
        else:
            d.text((x0 + 2, y0 + p + 2), str(mm), fill=LABEL, font=font)


def _matrix_labels(d, rect, spec, font):
    x0, y0, x1, y1 = _inner(rect)
    grays, widths = spec.matrix_grays, spec.feature_widths_px
    half = (x1 - x0 - 42) // 2
    pos_x0 = x0 + 42
    neg_x0 = pos_x0 + half + 12
    cell_w = half / len(widths)
    for j, wpx in enumerate(widths):
        um = round(wpx * spec.voxel_width_um)
        d.text((pos_x0 + j * cell_w + 1, y0 - 2), f"{um}", fill=LABEL, font=font)
        d.text((neg_x0 + j * cell_w + 1, y0 - 2), f"{um}", fill=LABEL, font=font)
    row_h = (y1 - y0) / len(grays)
    for i, g in enumerate(grays):
        d.text((x0, int(y0 + i * row_h + row_h / 2)), f"{g}", fill=LABEL, font=font)


def _squares_labels(d, rect, spec, font):
    x0, y0, x1, y1 = _inner(rect)
    px_mm = spec.voxel_width_um / 1000.0
    py_mm = spec.voxel_length_um / 1000.0
    ox, oy = x0 + 6, y1 - 6
    for mm in sorted(spec.block_mm, reverse=True):
        w = int(round(mm / px_mm)); h = int(round(mm / py_mm))
        if ox + w > x1 or oy - h < y0:
            continue
        d.text((ox + w - 34, oy - h + 4), f"{mm:g}", fill=LABEL, font=font)


# ── helpers ──────────────────────────────────────────────

def _inner(rect):
    """Content rect inside a card, reserving the title band (kept identical whether or
    not the card box is actually drawn, so gel + reference line up voxel-for-voxel)."""
    x0, y0, x1, y1 = rect
    return (x0 + 8, y0 + 30, x1 - 8, y1 - 8)


def _label(d, rect, title, font):
    x0, y0, x1, y1 = rect
    d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=LABEL_DIM, width=1)
    d.text((x0 + 6, y0 + 6), title, fill=LABEL, font=font)


def _font(size: int):
    for path in ("DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        import matplotlib
        return ImageFont.truetype(f"{matplotlib.get_data_path()}/fonts/ttf/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


# ── small 1 cm chip (bioprint-focused, genuinely 3D) ─────

def _small_quads(spec):
    """Centred chip square split into four quadrants (TL, BL, TR, BR)."""
    W, H = spec.width_px, spec.height_px
    side_x = round(spec.chip_mm / (spec.voxel_width_um / 1000.0))
    side_y = round(spec.chip_mm / (spec.voxel_length_um / 1000.0))
    cx0, cy0 = (W - side_x) // 2, (H - side_y) // 2
    cx1, cy1 = cx0 + side_x, cy0 + side_y
    mx, my = (cx0 + cx1) // 2, (cy0 + cy1) // 2
    g = 4
    return {
        "chip": (cx0, cy0, cx1, cy1),
        "tl": (cx0, cy0, mx - g, my - g),   # pyramids in (funnels)
        "bl": (cx0, my + g, mx - g, cy1),   # pyramids out (solid)
        "tr": (mx + g, cy0, cx1, my - g),   # buried channels
        "br": (mx + g, my + g, cx1, cy1),   # grayscale checker / variance
    }


def _small_layer(spec: CalibrationSpec, index: int) -> np.ndarray:
    """A 1 cm chip. Base = solid raft; feature layers build genuinely 3D features
    (tapering pyramids, roofed channels) so the pattern depends on the layer."""
    q = _small_quads(spec)
    img = Image.new("L", (spec.width_px, spec.height_px), 0)
    d = ImageDraw.Draw(img)
    cx0, cy0, cx1, cy1 = q["chip"]
    if index <= spec.base_layers:
        d.rectangle([cx0, cy0, cx1 - 1, cy1 - 1], fill=WHITE)
        return np.array(img, dtype=np.uint8)
    z, F, n = index - 1 - spec.base_layers, spec.feature_layers, spec.pyramid_grid
    _pyramids_in(d, q["tl"], z, F, n)
    _pyramids_out(d, q["bl"], z, F, n)
    _channels(d, q["tr"], spec.channel_count, spec.channel_max_px)
    _checker(d, q["br"], spec.checker_min, spec.checker_max)
    return np.array(img, dtype=np.uint8)


def _pyramid_bases(rect, n):
    """Base sizes (px) for an n x n grid, swept GEOMETRICALLY from ~2 px (probes the
    min-feature limit) up to ~0.9 of the cell, so the smallest pyramids/wells actually
    find the resolution limit. Same order as the drawn grid."""
    x0, y0, x1, y1 = rect
    cell = min((x1 - x0) / n, (y1 - y0) / n)
    total = n * n
    lo, hi = 2.0, max(3.0, cell * 0.9)
    return [lo * (hi / lo) ** (k / (total - 1) if total > 1 else 1.0) for k in range(total)]


def _grid_cells(rect, n):
    """Yield (cx, cy, base_px) for each cell of the n x n grid, base sizes from
    ``_pyramid_bases``."""
    x0, y0, x1, y1 = rect
    cw, ch = (x1 - x0) / n, (y1 - y0) / n
    bases = _pyramid_bases(rect, n)
    for k, (i, j) in enumerate((i, j) for i in range(n) for j in range(n)):
        yield x0 + (j + 0.5) * cw, y0 + (i + 0.5) * ch, bases[k]


def _pyramids_out(d, rect, z, F, n):
    """Solid square pyramids pointing UP: cross-section shrinks toward the tip as the
    layer rises. n x n of sweeping base sizes — tests self-support / which sizes hold."""
    t = z / max(1, F - 1)
    for cx, cy, base in _grid_cells(rect, n):
        s = base * (1.0 - t)
        if s >= 1:
            d.rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], fill=WHITE)


def _pyramids_in(d, rect, z, F, n):
    """Solid gel with pyramidal WELLS (funnels) that widen toward the top. n x n of
    sweeping sizes — tests whether wells stay open / don't over-cure shut."""
    x0, y0, x1, y1 = rect
    d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=WHITE)
    t = z / max(1, F - 1)
    for cx, cy, base in _grid_cells(rect, n):
        s = base * t
        if s >= 1:
            d.rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], fill=0)


def _channel_widths(count, max_px):
    return [max(1, round(1 + k * (max_px - 1) / max(1, count - 1))) for k in range(count)]


def _channels(d, rect, count, max_px):
    """Open horizontal channels (trenches) of sweeping width in a solid block. Open on
    top so they're visible/measurable from above — which widths stay patent vs pinch
    shut. Evenly distributed down the quadrant."""
    x0, y0, x1, y1 = rect
    d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=WHITE)
    widths = _channel_widths(count, max_px)
    avail = (y1 - y0) - 12
    gap = max(3.0, (avail - sum(widths)) / (count + 1))
    y = y0 + 6 + gap
    for w in widths:
        if y + w > y1 - 4:
            break
        d.rectangle([x0 + 6, round(y), x1 - 7, round(y) + w - 1], fill=0)
        y += w + gap


def _checker(d, rect, gmin, gmax):
    """Grayscale 'variance' checker: small cells cycling through 5 grays evenly spaced
    across [gmin, gmax], stepped along the diagonal — tests whether neighbouring pixels
    hold their separate exposures (cross-talk) over a chosen tone range."""
    x0, y0, x1, y1 = rect
    lo, hi = min(gmin, gmax), max(gmin, gmax)
    n = 5
    grays = [round(lo + k * (hi - lo) / (n - 1)) for k in range(n)]
    cell = 8
    for iy, yy in enumerate(range(y0, y1, cell)):
        for ix, xx in enumerate(range(x0, x1, cell)):
            d.rectangle([xx, yy, min(xx + cell, x1) - 1, min(yy + cell, y1) - 1],
                        fill=grays[(ix + iy) % n])


def _small_reference(spec: CalibrationSpec) -> np.ndarray:
    mid = spec.base_layers + max(1, spec.feature_layers // 2)
    gel = _small_layer(spec, mid)
    rgb = Image.fromarray(np.stack([gel // 2 + 40] * 3, axis=-1), "RGB")
    d = ImageDraw.Draw(rgb)
    q = _small_quads(spec)
    f_sm, f_md = _font(15), _font(20)
    cx0, cy0, cx1, cy1 = q["chip"]
    d.rectangle([cx0, cy0, cx1 - 1, cy1 - 1], outline=LABEL_DIM, width=1)
    d.text((cx0, cy0 - 24), f"SMALL CHIP  {spec.chip_mm:g} x {spec.chip_mm:g} mm  (mid layer)", fill=LABEL, font=f_md)
    for key, txt in (("tl", "Pyramids in (funnels)"), ("bl", "Pyramids out"),
                     ("tr", "Channels"), ("br", "Grayscale checker / variance")):
        x0, y0, x1, y1 = q[key]
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=LABEL_DIM, width=1)
        d.text((x0 + 4, y0 + 4), txt, fill=LABEL, font=f_sm)
    return np.array(rgb, dtype=np.uint8)


# ── measurement guide / answer key ───────────────────────

def answer_key(spec: CalibrationSpec) -> dict:
    if spec.variant == "small":
        px = spec.voxel_width_um
        return {
            "variant": "small",
            "chip_mm": spec.chip_mm,
            "pitch_um": [spec.voxel_width_um, spec.voxel_length_um],
            "layer_um": spec.voxel_height_um,
            "layers": {"base": spec.base_layers, "feature": spec.feature_layers},
            "zones": ["pyramids_in", "pyramids_out", "channels", "grayscale_checker"],
            "channel_widths_um": [round(w * px) for w in _channel_widths(spec.channel_count, spec.channel_max_px)],
            "checker_grays": [round(spec.checker_min + k * (spec.checker_max - spec.checker_min) / 4) for k in range(5)],
            "checker_cell_um": round(8 * px),
            "note": "3D chip (gel-only). Measure top-down footprint + which features survive.",
        }
    return {
        "canvas_px": [spec.width_px, spec.height_px],
        "pitch_um": [spec.voxel_width_um, spec.voxel_length_um],
        "layer_um": spec.voxel_height_um,
        "layers": {"base": spec.base_layers, "feature": spec.feature_layers},
        "blocks_mm": list(spec.block_mm),
        "wedge_grays": [round(i * 255 / (spec.wedge_steps - 1)) for i in range(spec.wedge_steps)],
        "matrix_grays": list(spec.matrix_grays),
        "feature_widths_um": [round(w * spec.voxel_width_um) for w in spec.feature_widths_px],
        "feature_widths_px": list(spec.feature_widths_px),
        "note": "Printed layers are gel-only; see reference.png for the labeled map.",
    }


def measurement_steps(spec: CalibrationSpec) -> list:
    """A curated, ordered list of measurement prompts for the step-by-step wizard (full
    chip only). Each step carries the nominal value + how to interpret the answer. The
    UI collects one measurement per step, then feeds them to ``solve``."""
    if spec.variant == "small":
        px = spec.voxel_width_um
        q = _small_quads(spec)
        pyr_um = sorted({round(b * px) for b in _pyramid_bases(q["bl"], spec.pyramid_grid)})
        chan_um = [round(w * px) for w in _channel_widths(spec.channel_count, spec.channel_max_px)]
        return [
            {"id": "min_pillar", "group": "Pyramids", "kind": "pick", "options": pyr_um,
             "prompt": "The solid pyramids run smallest → largest. Pick the SMALLEST that printed as a clean pyramid."},
            {"id": "min_well", "group": "Wells", "kind": "pick", "options": pyr_um,
             "prompt": "The funnel wells run smallest → largest. Pick the SMALLEST well that stayed open (didn't fill in)."},
            {"id": "min_channel", "group": "Channels", "kind": "pick", "options": chan_um,
             "prompt": "The channels run narrow → wide. Pick the NARROWEST channel still open (not fused shut)."},
            {"id": "checker_ok", "group": "Grayscale", "kind": "yesno",
             "prompt": "Are the grayscale checker cells distinct — each gray clearly separate, not bleeding together?"},
        ]
    px, py = spec.voxel_width_um, spec.voxel_length_um
    steps = []
    steps.append({"id": "comb_X", "group": "Scale", "zone": "comb", "axis": "X", "design_gray": 255,
                  "nominal_um": round(spec.width_px * px), "kind": "length",
                  "prompt": "Measure the TOP scale bar end-to-end (full width), in µm."})
    steps.append({"id": "comb_Y", "group": "Scale", "zone": "comb", "axis": "Y", "design_gray": 255,
                  "nominal_um": round(spec.height_px * py), "kind": "length",
                  "prompt": "Measure the LEFT scale bar end-to-end (full height), in µm."})
    blocks = sorted(set(spec.block_mm))
    for mm in ({blocks[len(blocks) // 2], blocks[-1]} if len(blocks) >= 2 else set(blocks)):
        for axis, pitch in (("X", px), ("Y", py)):
            steps.append({"id": f"sq{mm:g}_{axis}", "group": "Scale", "zone": "square", "axis": axis,
                          "design_gray": 255, "nominal_um": round(mm * 1000), "kind": "length",
                          "prompt": f"Nested {mm:g} mm square: measure its {axis} edge, in µm."})
    wmax = spec.feature_widths_px[-1]
    for g in spec.matrix_grays:
        steps.append({"id": f"pil_g{g}", "group": "Bloom", "zone": "matrix_pos", "axis": "-",
                      "design_gray": g, "nominal_um": round(wmax * px), "kind": "length",
                      "prompt": f"Pillar row gray={g}: measure the widest dot's diameter (µm). "
                                f"Enter 0 if that row didn't print."})
    steps.append({"id": "res", "group": "Resolution", "zone": "grating", "kind": "resolution",
                  "options": [round(w * px) for w in spec.feature_widths_px],
                  "prompt": "Finest line-pair block still resolved as separate lines? (pick the smallest that's clear)"})
    return steps


def measurement_csv(spec: CalibrationSpec) -> str:
    rows = ["zone,id,axis,design_gray,nominal_um,measured_um,notes"]
    px = spec.voxel_width_um
    if spec.variant == "small":
        side_px = spec.chip_mm * 1000.0 / px
        pyr_um = round(0.72 * (side_px / 4.0) * px)   # base of one pyramid (2x2 grid per quadrant)
        for k in range(4):
            rows.append(f"pyramid_out,p{k},base,255,{pyr_um},,formed?/slump")
            rows.append(f"pyramid_in,w{k},well,255,{pyr_um},,open?/shape")
        for w in _channel_widths(spec.channel_count, spec.channel_max_px):
            rows.append(f"channel,w{w},width,0,{round(w * px)},,open width")
        for k in range(5):
            g = round(spec.checker_min + k * (spec.checker_max - spec.checker_min) / 4)
            rows.append(f"checker,g{g},cell,{g},{round(8 * px)},,distinct? crosstalk?")
        return "\n".join(rows) + "\n"
    for mm in spec.block_mm:
        rows.append(f"square,{mm:g}mm,X,255,{mm * 1000:.0f},,frame edge")
        rows.append(f"square,{mm:g}mm,Y,255,{mm * 1000:.0f},,frame edge")
    for i in range(spec.wedge_steps):
        g = round(i * 255 / (spec.wedge_steps - 1))
        rows.append(f"wedge,step{i},-,{g},-,,present?/height")
    for g in spec.matrix_grays:
        for w in spec.feature_widths_px:
            rows.append(f"matrix_pos,g{g}_w{w},line,{g},{round(w * px)},,pillar width")
            rows.append(f"matrix_neg,g{g}_w{w},slot,{g},{round(w * px)},,groove width")
    for w in spec.feature_widths_px:
        rows.append(f"grating,w{w},pitch,255,{round(w * px)},,resolved? y/n")
    rows.append(f"comb,X,span,255,{spec.width_px * spec.voxel_width_um:.0f},,end-to-end")
    rows.append(f"comb,Y,span,255,{spec.height_px * spec.voxel_length_um:.0f},,end-to-end")
    return "\n".join(rows) + "\n"
