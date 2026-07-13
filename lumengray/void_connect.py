"""Algorithmic void-connector — link every tessellation void into one network.

Tessellations are *periodic*: one unit cell's void pattern repeats across the whole
part, regardless of the per-element grade or internal structure. So instead of a
brute-force 3D scan we plan the connecting channels on a SINGLE cell and tile them.

Tiling-connectivity theorem — the tiled union of ``(void | channel)`` is one connected
component iff
  (1) the cell's ``(void | channel)`` is connected, and
  (2) for each lattice generator, the two faces it separates share at least one common
      *transverse* point that lies in ``(void | channel)``.

We satisfy (2) with **geometry-driven ports**: project the cell's void *hub* (the
deepest void point, argmax of the void distance transform) onto each face and carve a
straight channel hub->face there. Because both opposite ports sit at the hub's shared
transverse coordinate, tiling lines neighbour ports up automatically — and the port
follows the actual void, not an arbitrary box centre. Condition (1) is met by linking
every void component in the cell to the hub, so a void->light->void grade (several
concentric void shells) joins into one piece.

Pure geometry (numpy/scipy). The caller supplies the cell's void volume ``V`` (shape
``(Lz, Ly, Lx)``, True = void) and does the per-layer tiling + carve.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def _ball(radius: int) -> np.ndarray:
    r = int(radius)
    zz, yy, xx = np.mgrid[-r:r + 1, -r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy + zz * zz) <= radius * radius


def _disk(radius: int) -> np.ndarray:
    r = int(radius)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= radius * radius


def _carve_segment_2d(center: np.ndarray, a, b, route: str = "geodesic") -> None:
    """2D analogue of _carve_segment (a, b are (row, col)); tpms deflects in-plane."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    d = b - a
    length = float(np.hypot(*d))
    curved = route == "tpms" and length > 2.0
    amp = min(length * 0.30, 2.5) if curved else 0.0
    steps = max(int(np.ceil((length + 6.0 * amp) * 3.0)), int(np.max(np.abs(d))), 1)
    ts = np.arange(steps + 1) / steps
    pts = a[None, :] + d[None, :] * ts[:, None]
    if curved:
        perp = np.array([-d[1], d[0]]) / (length + 1e-9)
        offset = amp * np.sin(np.pi * 3.0 * ts) * (1.0 - np.abs(2.0 * ts - 1.0))
        pts = pts + offset[:, None] * perp[None, :]
    p = np.round(pts).astype(int)
    for axis, hi in enumerate(center.shape):
        np.clip(p[:, axis], 0, hi - 1, out=p[:, axis])
    _write6(center, p)


def connect_components_2d(V2: np.ndarray, channel_px: int, route: str = "geodesic",
                          max_bridge: float | None = None) -> np.ndarray:
    """Link every 2D void component into one network via a closest-point-bridge MST.
    Candidate edges come from each component's nearest centroids (cheap), but each
    edge is carved between the two components' *closest sampled points* — so
    concentric shells (coincident centroids, e.g. a void->light->void grade) still
    bridge radially. Returns a boolean channel mask to extrude across the layers.

    ``max_bridge`` (px) caps how far a channel may reach: edges longer than it are
    dropped, so sparse/scattered voids (e.g. a linear grade that only touches 0 at a
    few rasterization-lucky centroids) are NOT joined by model-spanning lines. Voids
    that can't be reached locally are simply left separate — honest, not ugly."""
    labels, n = ndimage.label(V2)
    if n <= 1:
        return np.zeros_like(V2)
    from scipy.spatial import cKDTree

    slices = ndimage.find_objects(labels)
    cents = np.array(ndimage.center_of_mass(V2, labels, range(1, n + 1)))
    k = min(n, 6)
    _, idxs = cKDTree(cents).query(cents, k=k)

    _pix: dict = {}
    def pix(i: int) -> np.ndarray:
        if i not in _pix:
            sl = slices[i]
            rr, cc = np.where(labels[sl] == i + 1)
            rr = rr + sl[0].start
            cc = cc + sl[1].start
            if rr.size > 24:  # sample to bound the closest-pair cost
                sel = np.linspace(0, rr.size - 1, 24).astype(int)
                rr, cc = rr[sel], cc[sel]
            _pix[i] = np.column_stack([rr, cc])
        return _pix[i]

    max_d2 = (max_bridge * max_bridge) if max_bridge is not None else float("inf")
    edges = []
    for i in range(n):
        for j in idxs[i][1:]:
            j = int(j)
            if j <= i:
                continue
            ci, cj = pix(i), pix(j)
            d2 = ((ci[:, None, :] - cj[None, :, :]) ** 2).sum(-1)
            best = float(d2.min())
            if best > max_d2:  # too far to be a local link — never span the model
                continue
            fa, fb = np.unravel_index(int(d2.argmin()), d2.shape)
            edges.append((best, i, j, ci[fa], cj[fb]))
    edges.sort(key=lambda e: e[0])

    parent = list(range(n))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    center = np.zeros_like(V2)
    for _w, i, j, pa, pb in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            _carve_segment_2d(center, pa, pb, route)
    # No long-distance fallback: components that no capped edge reaches stay separate
    # (a spanning tree of a well-formed void lattice is fully connected by local edges
    # already; only genuinely-isolated noise is left alone — never bridged across the part).

    rad = (channel_px - 1) // 2
    return ndimage.binary_dilation(center, structure=_disk(rad)) if rad > 0 else center


def _write6(mask: np.ndarray, pts: np.ndarray) -> None:
    """Trace a 6-connected (face-connected) path through the integer points ``pts``
    into ``mask``. Consecutive points differ by <=1 per axis (dense sampling), so we
    insert staircase corners one axis at a time — a diagonal step becomes an L, which
    keeps a width-1 channel physically connected (no zero-area corner throats)."""
    cur = pts[0].copy()
    mask[tuple(cur)] = True
    for nxt in pts[1:]:
        for ax in range(mask.ndim):
            while cur[ax] != nxt[ax]:
                cur[ax] += 1 if nxt[ax] > cur[ax] else -1
                mask[tuple(cur)] = True


def _carve_segment(centerline: np.ndarray, a, b, route: str = "geodesic") -> None:
    """Rasterize a centerline from a to b into ``centerline`` (in place). ``geodesic``
    = straight; ``tpms`` = a curved path deflected sideways by a sinusoid that tapers
    to zero at both ends, so the endpoints stay anchored on the voids (still connects)
    while the channel reads as an organic minimal-surface curve."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    d = b - a
    length = float(np.linalg.norm(d))
    curved = route == "tpms" and length > 2.0
    amp = min(length * 0.30, 2.5) if curved else 0.0
    # Sample densely so consecutive centerline points stay well sub-voxel — a wavy
    # path covers more distance than the chord, so oversample by the amplitude. A
    # dense (<=1 voxel spacing) centerline is self-connected before any dilation.
    steps = max(int(np.ceil((length + 6.0 * amp) * 3.0)), int(np.max(np.abs(d))), 1)
    ts = np.arange(steps + 1) / steps
    pts = a[None, :] + d[None, :] * ts[:, None]
    if curved:
        u = d / length
        ref = np.array([0.0, 0.0, 1.0]) if abs(u[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        perp = np.cross(u, ref)
        perp = perp / (np.linalg.norm(perp) + 1e-9)
        taper = 1.0 - np.abs(2.0 * ts - 1.0)          # 0 at ends → anchored on the voids
        offset = amp * np.sin(np.pi * 3.0 * ts) * taper
        pts = pts + offset[:, None] * perp[None, :]
    p = np.round(pts).astype(int)
    for axis, hi in enumerate(centerline.shape):
        np.clip(p[:, axis], 0, hi - 1, out=p[:, axis])
    _write6(centerline, p)


def connect_cell(V: np.ndarray, channel_px: int, route: str = "geodesic") -> np.ndarray:
    """Return a boolean channel mask (same shape as ``V``) whose union with ``V``,
    when tiled, forms one connected network. ``channel_px`` is the tube width in
    voxels. ``route`` = "geodesic" (straight tubes) or "tpms" (organic curved tubes);
    both connect the SAME real voids — route only changes channel shape."""
    Lz, Ly, Lx = V.shape
    if not V.any():
        return np.zeros_like(V)

    edt = ndimage.distance_transform_edt(V)
    hub = np.array(np.unravel_index(int(np.argmax(edt)), V.shape))

    center = np.zeros_like(V)
    # (1) connect every void component to the hub (handles void->light->void shells).
    labels, ncomp = ndimage.label(V)
    for comp_id in range(1, ncomp + 1):
        comp = np.argwhere(labels == comp_id)
        nearest = comp[np.argmin(((comp - hub) ** 2).sum(axis=1))]
        _carve_segment(center, nearest, hub, route)

    # (2) geometry-driven ports: hub -> both faces of each axis at the hub's transverse
    #     coord, so tiling connects neighbour cells by construction.
    hz, hy, hx = hub
    faces = [
        (hz, hy, 0), (hz, hy, Lx - 1),   # -X / +X
        (hz, 0, hx), (hz, Ly - 1, hx),   # -Y / +Y
        (0, hy, hx), (Lz - 1, hy, hx),   # -Z / +Z
    ]
    for face in faces:
        _carve_segment(center, hub, face, "geodesic")  # ports stay straight so tiling always meets

    # Widen the (already 6-connected) centerline to a tube of diameter channel_px.
    # channel_px=1 → rad 0 → the bare 1-voxel channel, which stays connected because
    # _write6 laid it down face-connected (no reliance on dilation to bridge corners).
    rad = (channel_px - 1) // 2
    return ndimage.binary_dilation(center, structure=_ball(rad)) if rad > 0 else center
