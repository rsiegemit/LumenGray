"""Octet-truss tessellation — Buckminster-Fuller's space-filling tetrahedra +
octahedra (the FCC nearest-neighbour strut lattice).

Unlike the triangular *prism* mode (vertical columns + flat triangle frames),
the octet truss has **sloped** struts running diagonally between layers, so the
cells are true 3D pyramids/tetrahedra. We define it by its strut segments — the
exact same ones the 3D cage draws — and a voxel is white when it's within the
strut radius of one, so the printed photostack and the cage are one geometry.

Nodes sit on an FCC lattice: (i*hx, j*hx, k*hz) with i+j+k even, where hx is the
node spacing in XY pixels and hz in Z layers (anisotropy-friendly). Each node
joins its 12 nearest neighbours — the (+/-1,+/-1,0)-type directions.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import OctetTessellation
from .tessellation import _boundary_mask

# 6 forward directions (one per antipodal pair) → every edge emitted once.
_FWD = ((1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1), (0, 1, 1), (0, 1, -1))


def octet_struts(c0, r0, c1, r1, z0, z1, hx, hz):
    """Octet strut segments whose lower endpoint's node lies in the
    [c0,c1)x[r0,r1) x [z0,z1] window. Coords in (col_px, row_px, layer).
    Returns a list of (ax, ay, az, bx, by, bz)."""
    i0, i1 = int(np.floor(c0 / hx)) - 1, int(np.ceil(c1 / hx)) + 1
    j0, j1 = int(np.floor(r0 / hx)) - 1, int(np.ceil(r1 / hx)) + 1
    k0, k1 = int(np.floor(z0 / hz)) - 1, int(np.ceil(z1 / hz)) + 1
    segs = []
    for k in range(k0, k1 + 1):
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                if (i + j + k) & 1:
                    continue
                ax, ay, az = i * hx, j * hx, k * hz
                for di, dj, dk in _FWD:
                    segs.append((ax, ay, az, (i + di) * hx, (j + dj) * hx, (k + dk) * hz))
    return segs


def _disk(radius: float) -> np.ndarray:
    r = max(1, int(round(radius)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= radius * radius


def _skeleton(shape, z, oct: OctetTessellation) -> np.ndarray:
    """1-px strut skeleton crossing layer ``z`` (z = 0 at the first interior
    layer): the sloped-strut crossing points + the in-plane diagonal struts on a
    node plane. Dilated to thickness by the caller."""
    hx = oct.cell_xy_px / 2.0
    hz = oct.cell_z_layers / 2.0
    height, width = shape
    skel = np.zeros((height, width), dtype=bool)

    k = int(np.floor(z / hz + 1e-9))
    t = z / hz - k

    # Node (i, j) grid for plane k: i + j has the parity of k.
    ii = np.arange(-1, int(width / hx) + 2)
    jj = np.arange(-1, int(height / hx) + 2)
    I, J = np.meshgrid(ii, jj)
    keep = ((I + J + k) & 1) == 0
    nx = (I[keep] * hx)
    ny = (J[keep] * hx)

    def stamp(cx, cy):
        cxi = np.round(cx).astype(int)
        cyi = np.round(cy).astype(int)
        ok = (cxi >= 0) & (cxi < width) & (cyi >= 0) & (cyi < height)
        skel[cyi[ok], cxi[ok]] = True

    # Sloped struts up from plane k → crossing points at fraction t (4 families).
    off = t * hx
    stamp(nx + off, ny)
    stamp(nx - off, ny)
    stamp(nx, ny + off)
    stamp(nx, ny - off)

    # Horizontal (in-plane) struts: 45° diagonal lines through the nodes of any
    # node plane within the strut's Z half-thickness of this layer.
    z_half = max(1.0, float(oct.strut_px))
    for kk in (k, k + 1):
        if abs(z - kk * hz) <= z_half:
            X, Y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
            fx, fy = X / hx, Y / hx
            s1, s2 = fx + fy, fx - fy
            m1, m2 = np.round(s1), np.round(s2)
            d1 = np.abs(s1 - m1) * hx / np.sqrt(2.0)
            d2 = np.abs(s2 - m2) * hx / np.sqrt(2.0)
            pk = kk & 1
            skel |= (d1 <= 0.7) & ((m1.astype(int) & 1) == pk)
            skel |= (d2 <= 0.7) & ((m2.astype(int) & 1) == pk)
    return skel


def _octa_core(shape, z, oct: OctetTessellation) -> np.ndarray:
    """Octahedral void cells of the octet truss at layer ``z``. The octahedra are
    centred on the FCC *anti-nodes* (i+j+k odd) — the octet's natural octahedral
    holes — with L1 (diamond) radius ``core_px`` pixels in XY."""
    hx = oct.cell_xy_px / 2.0
    hz = oct.cell_z_layers / 2.0
    height, width = shape
    cr = min(float(oct.core_px), 0.9 * hx)  # void L1 half-extent in px (cap keeps struts)
    thresh = cr + 0.5  # half-pixel margin → the octahedron edge never lands on a pixel
    X, Y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    fi, fj = X / hx, Y / hx
    # Anti-nodes (octahedron centres, i+j+k odd) become a regular grid in the
    # rotated frame u=i+j, v=i-j, where the in-plane L1 distance = Chebyshev
    # distance to the nearest (parity, parity) point — exact and uniform.
    fu, fv = fi + fj, fi - fj
    fk = z / hz
    void = np.zeros((height, width), dtype=bool)
    for k in (int(np.floor(fk)), int(np.floor(fk)) + 1):
        zterm = abs(fk - k) * hx  # octahedron shrinks toward its top/bottom vertices
        if zterm >= thresh:
            continue
        p = (1 - (k & 1)) & 1  # u, v parity so that i+j+k is odd
        u = np.round((fu - p) / 2.0) * 2 + p
        v = np.round((fv - p) / 2.0) * 2 + p
        lxy = hx * np.maximum(np.abs(fu - u), np.abs(fv - v))  # L1 XY distance to centre (px)
        void |= (lxy + zterm) < thresh
    return void


def octet_core_depth(shape, z, oct: OctetTessellation) -> np.ndarray:
    """Inward-depth field for the structure->core gradient: 0 out at the FCC struts
    rising to 1 at the octahedral void centre (the cell core). A single 2D slice of
    the sloped strut lattice is too sparse for a distance transform, so grade
    radially from the octahedral centres (the octet's own void cells) instead — the
    same anti-node metric ``_octa_core`` uses — so it flows cleanly inward per cell
    at every layer. ``z`` = 0 at the first interior layer."""
    hx = oct.cell_xy_px / 2.0
    hz = oct.cell_z_layers / 2.0
    height, width = shape
    X, Y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    fi, fj = X / hx, Y / hx
    fu, fv = fi + fj, fi - fj  # rotated frame: octahedral centres form a regular grid
    fk = z / hz
    octa = np.full((height, width), np.inf, dtype=np.float32)
    for k in (int(np.floor(fk)), int(np.floor(fk)) + 1):
        zterm = abs(fk - k) * hx
        p = (1 - (k & 1)) & 1  # anti-node parity so i+j+k is odd
        u = np.round((fu - p) / 2.0) * 2 + p
        v = np.round((fv - p) / 2.0) * 2 + p
        lxy = hx * np.maximum(np.abs(fu - u), np.abs(fv - v))  # distance to nearest octa centre
        octa = np.minimum(octa, lxy + zterm)
    return np.clip(1.0 - octa / hx, 0.0, 1.0)  # 1 at the centre (core) -> 0 at the struts


def octet_layer(solid: np.ndarray, layer_index: int, total_layers: int, oct: OctetTessellation) -> np.ndarray:
    """One photostack layer of the octet truss: white struts, grey faces/core,
    solid-white caps, and a white outer-wall rim (1-indexed ``layer_index``)."""
    white = np.uint8(oct.white_value)
    layer = np.zeros(solid.shape, dtype=np.uint8)

    if layer_index <= oct.cap_bottom_layers or layer_index > total_layers - oct.cap_top_layers:
        return np.where(solid, white, layer)  # solid-white cap

    z = layer_index - 1 - oct.cap_bottom_layers  # 0 at the first interior layer
    skel = _skeleton(solid.shape, z, oct)
    strut = ndimage.binary_dilation(skel, structure=_disk(oct.strut_px))
    layer = np.where(solid, np.where(strut, white, np.uint8(oct.grey_value)), layer)

    # Black (void) core: an octahedron (the octet's own void cell) carved at each
    # cell centre. core_px ≈ the void's half-extent in XY pixels.
    if oct.core_px > 0:
        core = _octa_core(solid.shape, z, oct)
        layer = np.where(solid & core & ~strut, np.uint8(0), layer)

    rim = _boundary_mask(solid, oct.boundary_px)
    return np.where(rim, white, layer)


# ── self-test: the fast skeleton+dilation must match a brute-force voxelization
# of the strut segments (run: python -m lumengray.octet) ──────────────────────
if __name__ == "__main__":
    from dataclasses import replace
    oct = OctetTessellation(0, 0, 12, 10, 1, 0, 3, 128, 255)  # cell_xy=12, cell_z=10, strut=1, core=0
    hx, hz = oct.cell_xy_px / 2.0, oct.cell_z_layers / 2.0
    H = Wd = 48
    shell = float(oct.strut_px)
    struts = octet_struts(0, 0, Wd, H, -hz, 40 + hz, hx, hz)
    ys, xs = np.mgrid[0:H, 0:Wd]

    def brute(z):
        m = np.zeros((H, Wd), bool)
        for ax, ay, az, bx, by, bz in struts:
            lo, hi = min(az, bz), max(az, bz)
            if z < lo - 0.5 or z > hi + 0.5:
                continue
            if abs(bz - az) < 1e-9:
                if abs(z - az) > shell:
                    continue
                vx, vy = bx - ax, by - ay
                tt = np.clip(((xs - ax) * vx + (ys - ay) * vy) / (vx * vx + vy * vy + 1e-9), 0, 1)
                px, py = ax + tt * vx, ay + tt * vy
            else:
                s = (z - az) / (bz - az)
                if s < 0 or s > 1:
                    continue
                px, py = ax + s * (bx - ax), ay + s * (by - ay)
            m |= ((xs - px) ** 2 + (ys - py) ** 2) <= shell * shell
        return m

    # Structural check: every skeleton pixel must coincide with a real strut
    # crossing (thickness then comes from the dilation), across all layers.
    def crossings(z):
        pts = set()
        for ax, ay, az, bx, by, bz in struts:
            if abs(bz - az) < 1e-9:
                continue
            s = (z - az) / (bz - az)
            if 0 <= s <= 1:
                px, py = ax + s * (bx - ax), ay + s * (by - ay)
                if 0 <= px < Wd and 0 <= py < H:
                    pts.add((round(px, 2), round(py, 2)))
        return pts

    z_half = max(1.0, float(oct.strut_px))
    worst = 0
    for zL in range(2, 38):
        near_plane = min(abs(zL - kk * hz) for kk in range(0, 9)) <= z_half
        if near_plane:  # node-plane layers also carry horizontal struts (not in `crossings`)
            continue
        cx = crossings(zL)
        sk = _skeleton((H, Wd), zL, oct)
        extra = sum(
            0 if any((xx - a) ** 2 + (yy - b) ** 2 <= 1.0 for a, b in cx) else 1
            for yy, xx in zip(*np.where(sk))
        )
        worst = max(worst, extra)
    print("worst (pure-sloped layers) skeleton px with no matching strut:", worst, "→", "PASS" if worst == 0 else "FAIL")
