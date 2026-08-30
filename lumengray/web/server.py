"""FastAPI backend for LumenGray.

Thin HTTP layer over ``lumengray``: upload an STL, preview any single layer
live as parameters change, and export the full grayscale photostack as a zip.
All slicing/grayscale logic lives in the library; this module only wires it to
HTTP and keeps uploaded meshes warm in memory for fast previews.
"""

from __future__ import annotations

import base64
import gc
import io
import json
import os
import shutil
import tempfile
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, replace

import numpy as np
import trimesh
from scipy import ndimage
from fastapi import Cookie, Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from PIL import Image
from pydantic import BaseModel

from .. import __version__, calibration, calibration_solve
from ..config import ConfigError, config_from_dict
from ..octet import octet_struts
from ..pipeline import render_layer, resolve_regions, run
from ..preview import sample_indices
from ..slicer import array_mesh, canvas_origin, count_layers, load_mesh, orient_mesh, slice_index
from .presets import PRESETS, build_preset_mesh, get_preset, mode_of, resolve_params

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_UPLOADS = 64  # hard cap on the in-memory registry (shared/public deploys)
UPLOAD_TTL_SECONDS = 2 * 60 * 60  # reap models idle this long; each access refreshes the clock

GITHUB_REPO = "rsiegemit/LumenGray"
RELEASES_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


def _version_tuple(v: str) -> tuple:
    """Parse 'v1.2.3' / '1.2.3' → (1, 2, 3) for comparison; non-numeric parts → 0."""
    out = []
    for part in str(v).lstrip("vV").split(".")[:3]:
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) + (0,) * (3 - len(out))


@dataclass
class Upload:
    path: str
    name: str
    mesh: trimesh.Trimesh
    meta: dict  # origin: uploaded filename, or preset name + dimensions used
    owner: str | None = None  # session that uploaded it; only that session may read it back
    last_seen: float = 0.0  # monotonic clock of the last access; refreshed on every _get


class PresetRequest(BaseModel):
    params: dict | None = None


class PreviewRequest(BaseModel):
    id: str
    config: dict
    index: int = 1


class InfoRequest(BaseModel):
    id: str
    config: dict


class ExportRequest(BaseModel):
    id: str
    config: dict
    prefix: str = ""


class StackRequest(BaseModel):
    id: str
    config: dict
    max_layers: int = 64
    max_px: int = 220


class VoxelRequest(BaseModel):
    id: str
    config: dict
    target: int = 72  # ~voxels along the longest axis
    max_voxels: int = 90000
    include_void: bool = False  # also emit interior void voxels (value 0) for the black band
    peak: bool = False  # report each voxel's max exposure (band view) instead of the mean (volume)


class NativeRequest(BaseModel):
    id: str
    config: dict
    bands: list[str] = ["white", "gray", "black"]  # which to emit
    t_low: int = 64  # < t_low → black (lumen, interior void); < t_high → gray; else white
    t_high: int = 192
    layer_from: int = 1  # inclusive 1-based Z-slab window (bounds the work + transfer)
    layer_to: int = 0  # 0 → to the top
    max_voxels: int = 1_800_000  # hard cap (solid boxes are memory-heavy); over this → truncated


class ElementRequest(BaseModel):
    config: dict


class CalibrationRequest(BaseModel):
    config: dict           # supplies the printer (resolution + XY/Z voxel pitch)
    spec: dict | None = None
    index: int = 1
    view: str = "reference"  # "reference" (labeled map) | "print" (gel-only layer)


class SolveRequest(BaseModel):
    config: dict           # supplies the assumed XY pitch
    csv: str               # the filled-in measurement.csv text


class PrintCheckRequest(BaseModel):
    id: str
    config: dict
    limits: dict = {}      # {min_pillar_um, min_channel_um, ...} from the small-chip wizard
    samples: int = 16


class CageRequest(BaseModel):
    id: str
    config: dict
    max_segments: int = 120000


def _element_cell_struts(config):
    """Crisp strut segments of exactly ONE unit cell, in voxel coords
    (ax, ay, az, bx, by, bz) with x,y in pixels and z in layers. Returns
    (segments, cell_xy_px, cell_z_layers, hull_nodes) or None if no tessellation
    is active. ``hull_nodes`` (octet only) are the cell's corner nodes, used to
    clip the graded fill to the primitive's convex hull.

    An octet/triangular cell isn't a cube, so a voxel *block* can't hold one
    cleanly — instead we emit the cell's actual struts as lines (the print's
    graded fill is drawn separately inside this cage)."""
    if config.octet is not None:
        cx, cz = config.octet.cell_xy_px, config.octet.cell_z_layers
        hx, hz = cx / 2.0, cz / 2.0

        def P(i, j, k):
            return (i * hx, j * hx, k * hz)

        # The octet truss's faithful primitive unit: one octahedron centred on the
        # cell (anti-node (1,1,1)) with a tetrahedron capping two opposite faces
        # (apexes at the (0,0,0) and (2,2,2) corners) = 1 octahedron + 2 tetrahedra,
        # the tet:oct = 2:1 repeating unit that actually fills space.
        A, B, C, D, E, F = P(0, 1, 1), P(2, 1, 1), P(1, 0, 1), P(1, 2, 1), P(1, 1, 0), P(1, 1, 2)
        G, H = P(0, 0, 0), P(2, 2, 2)
        oct_edges = [(A, C), (A, D), (A, E), (A, F), (B, C), (B, D), (B, E), (B, F), (C, E), (C, F), (D, E), (D, F)]
        tet_edges = [(H, B), (H, D), (H, F), (G, A), (G, C), (G, E)]
        segs = [(*p, *q) for p, q in oct_edges + tet_edges]
        return segs, cx, cz, [A, B, C, D, E, F, G, H]
    if config.tessellation is not None:
        p, cz = config.tessellation.cube_xy_px, config.tessellation.cube_z_layers
        corners = [(0, 0), (p, 0), (p, p), (0, p)]
        segs = [(c, r, 0, c, r, cz) for c, r in corners]  # 4 vertical edge-columns
        for z in (0, cz):  # bottom + top square frames
            segs += [(corners[i][0], corners[i][1], z, corners[(i + 1) % 4][0], corners[(i + 1) % 4][1], z) for i in range(4)]
        return segs, p, cz, None
    if config.triangulation is not None:
        tp, cz = config.triangulation.tri_px, config.triangulation.z_layers
        sp = tp * (3.0 ** 0.5) / 2.0  # triangle height (row spacing)
        verts = [(0.0, 0.0), (float(tp), 0.0), (tp / 2.0, sp)]  # one upward triangle
        segs = [(c, r, 0, c, r, cz) for c, r in verts]  # 3 vertical edge-columns
        for z in (0, cz):  # bottom + top triangle frames
            segs += [(verts[i][0], verts[i][1], z, verts[(i + 1) % 3][0], verts[(i + 1) % 3][1], z) for i in range(3)]
        return segs, tp, cz, None
    return None


def create_app() -> FastAPI:
    app = FastAPI(title="LumenGray", version=__version__)
    uploads: dict[str, Upload] = {}
    upload_dir = tempfile.mkdtemp(prefix="lumengray_uploads_")

    @app.middleware("http")
    async def _no_cache(request, call_next):
        # Local tool: never let the browser serve stale UI assets.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _session(response: Response, lg_session: str | None = Cookie(default=None)) -> str:
        # Per-browser session id so one visitor's uploaded model isn't reachable by
        # another on a shared (public) deployment. Set on first request; local
        # single-user runs just keep one cookie for the life of the tab.
        if lg_session:
            return lg_session
        new_id = uuid.uuid4().hex
        response.set_cookie(
            "lg_session", new_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7
        )
        return new_id

    def _get(upload_id: str, session: str | None = None) -> Upload:
        item = uploads.get(upload_id)
        # Same 404 for missing and not-yours, so an id can't be probed for existence.
        if item is None or (item.owner is not None and item.owner != session):
            raise HTTPException(404, "Unknown model id - upload an STL first")
        item.last_seen = time.monotonic()  # touch → an in-use model is never the reaper's victim
        return item

    def _config(raw: dict):
        try:
            return config_from_dict(raw)
        except ConfigError as error:
            raise HTTPException(400, str(error)) from error

    def _oriented(item: Upload, config) -> trimesh.Trimesh:
        # orient_mesh mutates in place, so always work on a copy of the cached mesh.
        mesh = orient_mesh(item.mesh.copy(), config.rotation_deg)
        return array_mesh(mesh, config.array_count, config.array_spacing_mm)

    def _drop(upload_id: str) -> None:
        item = uploads.pop(upload_id, None)
        if item is None:
            return
        try:
            if os.path.exists(item.path):
                os.remove(item.path)
        except OSError:
            pass

    def _reap() -> None:
        # Keep the in-memory registry (and its temp files) bounded on a long-lived shared
        # deploy WITHOUT evicting a model that's actively in use: first drop anything idle
        # past the TTL, then, if still over the hard cap, drop least-recently-used (smallest
        # last_seen) — and an in-use model has a fresh last_seen, so it's never the victim.
        now = time.monotonic()
        for uid in [uid for uid, it in uploads.items() if now - it.last_seen > UPLOAD_TTL_SECONDS]:
            _drop(uid)
        while len(uploads) > MAX_UPLOADS:
            lru_id = min(uploads, key=lambda uid: uploads[uid].last_seen)
            _drop(lru_id)

    def _register(mesh: trimesh.Trimesh, name: str, meta: dict, owner: str | None = None) -> dict:
        upload_id = uuid.uuid4().hex
        path = os.path.join(upload_dir, f"{upload_id}.stl")
        mesh.export(path)
        uploads[upload_id] = Upload(
            path=path, name=name, mesh=mesh, meta=meta, owner=owner, last_seen=time.monotonic()
        )
        _reap()
        extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()
        return {
            "id": upload_id,
            "name": name,
            "extents_mm": [round(v, 3) for v in extents],
            "watertight": bool(mesh.is_watertight),
            "triangles": int(len(mesh.faces)),
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.post("/api/upload")
    async def upload(file: UploadFile, session: str = Depends(_session)) -> dict:
        data = await file.read()
        if not data:
            raise HTTPException(400, "Empty file")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large (limit 100 MB)")
        tmp = os.path.join(upload_dir, f"{uuid.uuid4().hex}.upload.stl")
        with open(tmp, "wb") as handle:
            handle.write(data)
        try:
            mesh = load_mesh(tmp)
        except Exception as error:  # noqa: BLE001 - surface any STL load failure as 400
            raise HTTPException(400, f"Could not read STL: {error}") from error
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        name = file.filename or "model.stl"
        return _register(mesh, name, {"kind": "upload", "filename": name}, owner=session)

    @app.get("/api/presets")
    def presets() -> list[dict]:
        out = []
        for preset in PRESETS:
            mesh = build_preset_mesh(preset["id"])
            extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()
            out.append(
                {
                    "id": preset["id"],
                    "name": preset["name"],
                    "description": preset["description"],
                    "params": preset["params"],  # editable mm dimensions
                    "extents_mm": [round(v, 1) for v in extents],
                    "mode": mode_of(preset["config"]),
                }
            )
        return out

    @app.post("/api/preset/{preset_id}")
    def load_preset(preset_id: str, req: PresetRequest | None = None, session: str = Depends(_session)) -> dict:
        preset = get_preset(preset_id)
        if preset is None:
            raise HTTPException(404, "Unknown preset")
        overrides = req.params if req else None
        values = resolve_params(preset, overrides)
        try:
            mesh = preset["build"](values)
        except Exception as error:  # noqa: BLE001 - bad dimensions → 400, not 500
            raise HTTPException(400, f"Could not build model: {error}") from error
        meta = {"kind": "preset", "preset_id": preset_id, "name": preset["name"], "dimensions_mm": values}
        result = _register(mesh, f"{preset['name']}.stl", meta, owner=session)
        result["config"] = preset["config"]
        result["params"] = preset["params"]
        result["values"] = values
        return result

    @app.get("/api/model/{upload_id}")
    def model(upload_id: str, session: str = Depends(_session)) -> FileResponse:
        item = _get(upload_id, session)
        return FileResponse(item.path, media_type="model/stl", filename=item.name)

    @app.post("/api/info")
    def info(req: InfoRequest, session: str = Depends(_session)) -> dict:
        item = _get(req.id, session)
        config = _config(req.config)
        mesh = _oriented(item, config)
        extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()
        return {
            "total_layers": count_layers(mesh, config.printer),
            "resolution": list(config.printer.resolution),
            "extents_mm": [round(v, 3) for v in extents],
            "mode": (
                "triangular_tessellation" if config.triangulation is not None
                else "cubic_tessellation" if config.tessellation is not None
                else "regions"
            ),
        }

    @app.post("/api/preview")
    def preview(req: PreviewRequest, session: str = Depends(_session)) -> Response:
        item = _get(req.id, session)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        index = max(1, min(req.index, total))
        try:
            solid = slice_index(mesh, config.printer, config.center_xy, index)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        origin = canvas_origin(mesh, config.printer, config.center_xy)
        regions = resolve_regions(config, origin)
        pixel_mm = config.printer.voxel_width_um / 1000.0
        layer = render_layer(solid, index, total, config, regions, pixel_mm)
        buffer = io.BytesIO()
        Image.fromarray(layer, mode="L").save(buffer, format="PNG")
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={"X-Total-Layers": str(total), "X-Layer-Index": str(index)},
        )

    @app.post("/api/export")
    def export(req: ExportRequest, session: str = Depends(_session)) -> FileResponse:
        item = _get(req.id, session)
        config = _config(req.config)
        work_dir = tempfile.mkdtemp(prefix="lumengray_export_")
        out_dir = os.path.join(work_dir, "layers")
        os.makedirs(out_dir, exist_ok=True)
        try:
            # run() writes the PNG layers AND a manifest.json (source + every setting).
            summary = run(item.path, out_dir, config, name_prefix=req.prefix, source=item.meta)
            # Stream the zip to disk (not an in-memory BytesIO) and delete each
            # file as it is archived so neither RAM nor disk holds the full stack
            # twice — building the whole zip in memory is what OOMs small hosts.
            zip_path = os.path.join(work_dir, "photostack.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for filename in sorted(os.listdir(out_dir)):
                    src = os.path.join(out_dir, filename)
                    archive.write(src, filename)
                    os.remove(src)
        except (ValueError, ConfigError) as error:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(400, str(error)) from error
        except BaseException:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        gc.collect()
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{summary['name']}.zip",
            background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
        )

    @app.post("/api/stack")
    def stack(req: StackRequest, session: str = Depends(_session)) -> dict:
        item = _get(req.id, session)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        origin = canvas_origin(mesh, config.printer, config.center_xy)
        regions = resolve_regions(config, origin)
        pixel_mm = config.printer.voxel_width_um / 1000.0
        layer_mm = config.printer.voxel_height_um / 1000.0

        x0, y0, x1, y1 = _footprint_box(mesh, config)
        if x1 <= x0 or y1 <= y0:
            raise HTTPException(400, "Model footprint is outside the build area")
        crop_w, crop_h = x1 - x0, y1 - y0
        scale = min(1.0, req.max_px / max(crop_w, crop_h))
        out_w, out_h = max(1, round(crop_w * scale)), max(1, round(crop_h * scale))

        count = max(1, min(req.max_layers, total))
        layers = []
        # Stream: render → crop → encode one layer at a time and let each full-res
        # array be freed before the next. Holding all sampled layers at once is what
        # OOMs small hosts (64 × 1920×1080 ≈ 130 MB).
        for i0 in sample_indices(total, count):
            idx = i0 + 1
            layer = render_layer(slice_index(mesh, config.printer, config.center_xy, idx), idx, total, config, regions, pixel_mm)
            crop = layer[y0:y1, x0:x1]
            # gray RGB; alpha = gray so background is transparent and grey cores
            # read as semi-transparent while white shells stay opaque.
            rgba = np.dstack([crop, crop, crop, crop])
            img = Image.fromarray(rgba, "RGBA").resize((out_w, out_h), Image.NEAREST)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            layers.append(
                {
                    "z_mm": round((idx - 0.5) * layer_mm, 4),
                    "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
                }
            )
            del layer, crop, rgba, img, buffer
        gc.collect()
        return {
            "count": len(layers),
            "total_layers": total,
            "plane_w_mm": round(crop_w * pixel_mm, 4),
            "plane_h_mm": round(crop_h * pixel_mm, 4),
            "height_mm": round(total * layer_mm, 4),
            "layers": layers,
        }

    @app.post("/api/voxels")
    def voxels(req: VoxelRequest, session: str = Depends(_session)) -> dict:
        item = _get(req.id, session)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")

        pixel_mm = config.printer.voxel_width_um / 1000.0
        length_mm = config.printer.voxel_length_um / 1000.0
        layer_mm = config.printer.voxel_height_um / 1000.0
        height = config.printer.resolution[1]  # for the row→world-Y flip below
        origin = canvas_origin(mesh, config.printer, config.center_xy)
        regions = resolve_regions(config, origin)

        # Model XY footprint in pixels so we don't voxelize empty canvas.
        c0, r0, c1, r1 = _footprint_box(mesh, config)
        if c1 <= c0 or r1 <= r0:
            raise HTTPException(400, "Model footprint is outside the build area")
        crop_w, crop_h = c1 - c0, r1 - r0

        height_mm = total * layer_mm
        max_dim_mm = max(crop_w * pixel_mm, crop_h * pixel_mm, height_mm)
        voxel_mm = max(max_dim_mm / max(8, req.target), pixel_mm)
        fxy = max(1, round(voxel_mm / pixel_mm))
        fz = max(1, round(voxel_mm / layer_mm))
        ncx, ncy, nz = -(-crop_w // fxy), -(-crop_h // fxy), -(-total // fz)
        if req.peak:
            # The band view is rendered as a wireframe, so striding the voxel list
            # (the sampler's memory cap) aliases with the row-major grid and punches
            # axis-aligned gaps. Coarsen until the whole grid fits under the cap so
            # nothing is dropped — bigger voxels, but gapless and still bounded.
            while ncx * ncy * nz > req.max_voxels:
                fxy += 1
                fz += 1
                ncx, ncy, nz = -(-crop_w // fxy), -(-crop_h // fxy), -(-total // fz)

        sampler = _BoundedSampler(req.max_voxels)
        for kz in range(nz):
            if req.peak:
                # Band view: collapse every layer in this Z-slab (elementwise max)
                # so thin frames/columns at any depth survive — keeps the lattice
                # connected through the height instead of sampling one center layer.
                lo = kz * fz
                hi = min(total, lo + fz)
                crop = None
                for li in range(lo, hi):
                    idx = li + 1
                    layer = render_layer(slice_index(mesh, config.printer, config.center_xy, idx), idx, total, config, regions, pixel_mm)
                    sub = layer[r0:r1, c0:c1]
                    crop = sub.astype(np.float32) if crop is None else np.maximum(crop, sub)
                    del layer, sub
            else:
                idx = min(total, kz * fz + fz // 2 + 1)  # center layer of the slab → fills the height
                layer = render_layer(slice_index(mesh, config.printer, config.center_xy, idx), idx, total, config, regions, pixel_mm)
                crop = layer[r0:r1, c0:c1].astype(np.float32)
                del layer
            padded = np.zeros((ncy * fxy, ncx * fxy), dtype=np.float32)
            padded[:crop_h, :crop_w] = crop
            del crop
            blocks = padded.reshape(ncy, fxy, ncx, fxy)
            solid = blocks > 0
            count = solid.sum(axis=(1, 3))
            # Volume shading wants the mean exposure; the band view wants the peak
            # so a thin white strut in a mostly-grey cell still reads as white
            # ("anywhere the photostack yields white"), not averaged away.
            if req.peak:
                value = blocks.max(axis=(1, 3))
            else:
                value = np.where(count > 0, blocks.sum(axis=(1, 3)) / np.maximum(count, 1), 0)
            # Interior voids: 0-pixels enclosed by solid (the carved core pockets),
            # excluding the empty exterior. A block counts as void if it is mostly
            # enclosed-void and has no cured pixels.
            if req.include_void:
                solid_px = padded > 0
                void_px = ndimage.binary_fill_holes(solid_px) & ~solid_px
                void_count = void_px.reshape(ncy, fxy, ncx, fxy).sum(axis=(1, 3))
                del solid_px, void_px
            del padded, blocks, solid
            z_mm = (kz * fz + fz / 2.0) * layer_mm
            rows, cols = np.where(count > 0)
            for cy, cx in zip(rows, cols):
                x_mm = (c0 + cx * fxy + fxy / 2.0) * pixel_mm
                y_mm = (height - 1 - (r0 + cy * fxy + fxy / 2.0)) * pixel_mm
                sampler.add([round(float(x_mm), 3), round(float(y_mm), 3), round(float(z_mm), 3), int(value[cy, cx])])
            if req.include_void:
                vrows, vcols = np.where((count == 0) & (void_count > (fxy * fxy) // 2))
                for cy, cx in zip(vrows, vcols):
                    x_mm = (c0 + cx * fxy + fxy / 2.0) * pixel_mm
                    y_mm = (height - 1 - (r0 + cy * fxy + fxy / 2.0)) * pixel_mm
                    sampler.add([round(float(x_mm), 3), round(float(y_mm), 3), round(float(z_mm), 3), 0])
                del void_count, vrows, vcols
            del count, value, rows, cols

        gc.collect()
        truncated = sampler.total > req.max_voxels
        out = sampler.result()
        return {
            "voxel_size_mm": [round(fxy * pixel_mm, 4), round(fxy * length_mm, 4), round(fz * layer_mm, 4)],
            "voxels": out,
            "count": len(out),
            "truncated": truncated,
            "height_mm": round(height_mm, 4),
        }


    @app.post("/api/cage")
    def cage(req: CageRequest, session: str = Depends(_session)) -> dict:
        """Procedural strut-edge cage for a tessellation: the vertical columns at
        the grid nodes + the horizontal frame edges, drawn as crisp 3D line
        segments computed from the lattice parameters (clipped to the part's
        footprint). Shows the cubic/triangular lattice the coarse voxel view can't
        resolve. Returns [] for non-tessellation modes."""
        item = _get(req.id, session)
        config = _config(req.config)
        cub, tri, oct = config.tessellation, config.triangulation, config.octet
        if cub is None and tri is None and oct is None:
            return {"segments": [], "kind": None, "height_mm": 0.0, "count": 0, "truncated": False}

        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        pixel_mm = config.printer.voxel_width_um / 1000.0
        length_mm = config.printer.voxel_length_um / 1000.0
        layer_mm = config.printer.voxel_height_um / 1000.0
        width, height = config.printer.resolution
        height_mm = total * layer_mm

        # Candidate-node window from the model's XY bounds; each Z level below is
        # clipped to ITS OWN slice silhouette, so frames and columns follow curves.
        c0, r0, c1, r1 = _footprint_box(mesh, config)

        def to_mm(col, row, z):
            return [round(col * pixel_mm, 3), round((height - 1 - row) * length_mm, 3), round(z, 3)]

        def solid_at(mask, col, row):
            r, c = int(round(row)), int(round(col))
            return 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and bool(mask[r, c])

        if oct is not None:
            # Octet truss: the actual sloped strut segments (same as the print),
            # clipped to the part by checking each endpoint against its node-plane
            # silhouette. z = 0 at the first interior layer.
            hx, hz = oct.cell_xy_px / 2.0, oct.cell_z_layers / 2.0
            lo, hi = oct.cap_bottom_layers + 1, total - oct.cap_top_layers
            zspan = max(0, hi - lo)
            kmax = int(zspan / hz) + 1
            masks = {}
            for k in range(-1, kmax + 2):
                L = int(round(lo + k * hz))
                if 1 <= L <= total:
                    masks[k] = slice_index(mesh, config.printer, config.center_xy, L)

            def node_solid(col, row, zrel):
                m = masks.get(int(round(zrel / hz)))
                return m is not None and solid_at(m, col, row)

            segs = []
            for ax, ay, az, bx, by, bz in octet_struts(c0, r0, c1, r1, 0, zspan, hx, hz):
                if node_solid(ax, ay, az) and node_solid(bx, by, bz):
                    za = (lo - 0.5 + az) * layer_mm
                    zb = (lo - 0.5 + bz) * layer_mm
                    segs.append(to_mm(ax, ay, za) + to_mm(bx, by, zb))
                    if len(segs) > req.max_segments:
                        break
            return {
                "segments": segs[: req.max_segments],
                "kind": "octet",
                "height_mm": round(height_mm, 4),
                "count": min(len(segs), req.max_segments),
                "truncated": len(segs) > req.max_segments,
            }

        if cub is not None:
            kind, p, period = "cubic", cub.cube_xy_px, cub.cube_z_layers
            cap_b, cap_t = cub.cap_bottom_layers, cub.cap_top_layers
            nodes = [(c, r) for r in range((r0 // p) * p, r1, p) for c in range((c0 // p) * p, c1, p)]
            neighbours = lambda c, r: ((c + p, r), (c, r + p))  # right + down (square grid)
        else:
            kind, tp, period = "triangular", tri.tri_px, tri.z_layers
            cap_b, cap_t = tri.cap_bottom_layers, tri.cap_top_layers
            sp = tp * (3.0 ** 0.5) / 2.0  # row spacing (perpendicular family distance)
            nodes, r_idx = [], int(r0 // sp)
            row = r_idx * sp
            while row < r1:
                offset = (r_idx % 2) * (tp / 2.0)  # odd rows offset half a cell
                col = offset + ((c0 - offset) // tp) * tp
                while col < c1:
                    if col >= 0:
                        nodes.append((col, row))
                    col += tp
                r_idx += 1
                row = r_idx * sp
            neighbours = lambda c, r: ((c + tp, r), (c + tp / 2.0, r + sp), (c - tp / 2.0, r + sp))

        # Z sampling levels: every frame layer (where the bracing frames sit) plus
        # the first/last interior layer so columns reach the caps. Cap the slice
        # count for very tall models.
        lo, hi = cap_b + 1, total - cap_t
        frame_layers = list(range(lo, hi + 1, period))
        levels = sorted(set([lo] + frame_layers + [hi]))
        if len(levels) > 80:
            keep = set(levels[:: -(-len(levels) // 80)]) | {lo, hi}
            frame_layers = [L for L in frame_layers if L in keep]
            levels = sorted(keep | set(frame_layers))
        frame_set = set(frame_layers)
        level_z = {L: (L - 0.5) * layer_mm for L in levels}

        present = [[False] * len(levels) for _ in nodes]
        segs = []
        for li, L in enumerate(levels):
            mask = slice_index(mesh, config.printer, config.center_xy, L)
            z = level_z[L]
            for ni, (c, r) in enumerate(nodes):
                if solid_at(mask, c, r):
                    present[ni][li] = True
            if L in frame_set:  # frame edges, clipped to this layer's silhouette
                for ni, (c, r) in enumerate(nodes):
                    if not present[ni][li]:
                        continue
                    for c2, r2 in neighbours(c, r):
                        if solid_at(mask, c2, r2):
                            segs.append(to_mm(c, r, z) + to_mm(c2, r2, z))
                if len(segs) > req.max_segments:
                    break
            del mask

        # Vertical columns over each run of consecutive in-part levels (so a column
        # only spans the height where the part actually covers that node).
        if len(segs) <= req.max_segments:
            for ni, (c, r) in enumerate(nodes):
                pr, li = present[ni], 0
                n = len(levels)
                while li < n:
                    if pr[li]:
                        start = li
                        while li + 1 < n and pr[li + 1]:
                            li += 1
                        if li > start:
                            segs.append(to_mm(c, r, level_z[levels[start]]) + to_mm(c, r, level_z[levels[li]]))
                    li += 1
                if len(segs) > req.max_segments:
                    break

        truncated = len(segs) > req.max_segments
        return {
            "segments": segs[: req.max_segments],
            "kind": kind,
            "height_mm": round(height_mm, 4),
            "count": min(len(segs), req.max_segments),
            "truncated": truncated,
        }

    @app.post("/api/native")
    def native(req: NativeRequest, session: str = Depends(_session)) -> Response:
        """1:1 machine-resolution voxels: every voxel is exactly one print pixel
        (35µm XY) × one layer (50µm Z), coloured by its real exposure and filtered
        to the requested bands (white=structure, gray=diffusion, black=lumen/void).
        Streams a compact binary blob (int16 x,y,layer + uint8 exposure value 0-255);
        metadata in the X-Meta header. Capped at max_voxels with a truncated flag.
        The band checkboxes are filters (which voxels to include); each voxel carries
        its true grayscale value so the view shows the full gradient, not 3 buckets."""
        item = _get(req.id, session)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        pixel_mm = config.printer.voxel_width_um / 1000.0
        layer_mm = config.printer.voxel_height_um / 1000.0
        width, height = config.printer.resolution
        regions = resolve_regions(config, canvas_origin(mesh, config.printer, config.center_xy))
        c0, r0, c1, r1 = _footprint_box(mesh, config)
        tl, th = req.t_low, req.t_high
        want = set(req.bands)
        cols, rows, lays, vals = [], [], [], []
        counts = {"white": 0, "gray": 0, "black": 0}
        nvox, truncated = 0, False
        lo = max(1, req.layer_from)
        hi = total if req.layer_to <= 0 else min(total, req.layer_to)

        for L in range(lo, hi + 1):
            sld = slice_index(mesh, config.printer, config.center_xy, L)
            lay = render_layer(sld, L, total, config, regions, pixel_mm)
            crop = lay[r0:r1, c0:c1]
            picks = []
            if "white" in want:
                m = crop >= th; counts["white"] += int(m.sum()); picks.append(m)
            if "gray" in want:
                m = (crop >= tl) & (crop < th); counts["gray"] += int(m.sum()); picks.append(m)
            if "black" in want:  # lumen: dark voxels WITHIN the solid body (carved cores /
                # channels / gradient-to-black). Use the RAW silhouette, not hole-filled —
                # an open hole (e.g. a torus centre) is not part of the body, so it must
                # not be counted as void.
                foot = sld[r0:r1, c0:c1]
                m = foot & (crop < tl); counts["black"] += int(m.sum()); picks.append(m)
            for m in picks:
                yy, xx = np.where(m)
                if yy.size:
                    cols.append((xx + c0).astype(np.int16))
                    rows.append((yy + r0).astype(np.int16))
                    lays.append(np.full(yy.size, L, np.int16))
                    vals.append(crop[yy, xx].astype(np.uint8))  # true 0-255 exposure per voxel
                    nvox += yy.size
            del lay, crop
            if nvox > req.max_voxels:
                truncated = True
                break

        if cols:
            cx = np.concatenate(cols)[: req.max_voxels]
            cy = np.concatenate(rows)[: req.max_voxels]
            cz = np.concatenate(lays)[: req.max_voxels]
            cv = np.concatenate(vals)[: req.max_voxels]
        else:
            cx = cy = cz = np.empty(0, np.int16); cv = np.empty(0, np.uint8)
        n = int(cx.size)
        buf = cx.tobytes() + cy.tobytes() + cz.tobytes() + cv.tobytes()
        meta = {
            "n": n, "pixel_mm": round(pixel_mm, 5), "layer_mm": round(layer_mm, 5),
            "height": height, "height_mm": round(total * layer_mm, 4), "total_layers": total,
            "layer_from": lo, "layer_to": hi, "truncated": truncated, "counts": counts,
        }
        gc.collect()
        return Response(content=buf, media_type="application/octet-stream", headers={"X-Meta": json.dumps(meta)})

    @app.post("/api/element")
    def element(req: ElementRequest) -> dict:
        """ONE tessellation unit cell for the gradient designer: the cell's crisp
        strut segments (drawn as a wireframe cage) plus the print's graded grey->
        black infill inside it (the structure->core gradient). No mesh needed. The
        part-level caps and outer-wall rim are zeroed (they're part-level, not the
        repeating unit). Returns struts [mm segments] + fill voxels [col,row,layer,value]."""
        config = _config(req.config)
        info = _element_cell_struts(config)
        if info is None:
            return {"struts": [], "voxels": [], "cell_mm": [0, 0, 0], "voxel_size_mm": [0, 0, 0], "count": 0}
        segs_vox, cx, cz, hull_nodes = info
        if config.octet is not None:
            grey = config.octet.grey_value
            config = replace(config, octet=replace(config.octet, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0))
        elif config.tessellation is not None:
            grey = config.tessellation.grey_value
            config = replace(config, tessellation=replace(config.tessellation, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0))
        else:
            grey = config.triangulation.grey_value
            config = replace(config, triangulation=replace(config.triangulation, cap_bottom_layers=0, cap_top_layers=0, boundary_px=0))

        pixel_mm = config.printer.voxel_width_um / 1000.0
        length_mm = config.printer.voxel_length_um / 1000.0
        layer_mm = config.printer.voxel_height_um / 1000.0
        struts = [[round(v, 4) for v in (s[0] * pixel_mm, s[1] * length_mm, s[2] * layer_mm,
                                         s[3] * pixel_mm, s[4] * length_mm, s[5] * layer_mm)] for s in segs_vox]

        # Graded infill: one cell's interior, keeping only the graded grey->black
        # fill (< white) — the white struts are drawn as the clean cage above.
        # One cell's XY footprint: a square for cubic/octet, the actual triangle for
        # triangular prisms (so the graded fill doesn't bleed into neighbour cells).
        hull = None
        if config.triangulation is not None:
            tp = config.triangulation.tri_px
            sp = tp * (3.0 ** 0.5) / 2.0
            yy, xx = np.mgrid[0:cx, 0:cx].astype(np.float64)
            solid = (yy <= sp + 0.5) & (xx >= yy * (tp / 2.0) / sp - 0.5) & (xx <= tp - yy * (tp / 2.0) / sp + 0.5)
        else:
            solid = np.ones((cx, cx), dtype=bool)
            if hull_nodes is not None:  # octet: clip the fill to the primitive's convex hull
                from scipy.spatial import Delaunay
                hull = Delaunay(np.array(hull_nodes, dtype=np.float64))
                gy, gx = np.mgrid[0:cx, 0:cx]
                grid_xy = np.column_stack([gx.ravel().astype(np.float64), gy.ravel().astype(np.float64)])
        # Show the grey fill and everything darker (the gradient's darkening toward
        # the core, or an explicit black core). For cubic/triangular that excludes
        # the near-strut white voxels — they just duplicate the cage and plain grey
        # already fills those cells. The octet primitive is different: its two
        # tetrahedral caps (the poles at the (0,0,0)/(2,2,2) apex nodes) are made
        # *entirely* of struts, so dropping white would leave the poles empty. There
        # we keep every interior voxel — struts included — so the cell renders as the
        # solid repeating unit and reads as one recognizable cell.
        keep_below = grey
        keep_all = hull is not None  # octet primitive: include struts to fill the tet caps
        fill = []
        # Render z = 0..cz (node plane to node plane) so the fill spans exactly the
        # same range as the strut cage; store z in the SAME units as the struts
        # (octet layers, 0-based) so cage and fill line up voxel-for-voxel.
        for L in range(1, cz + 2):  # caps zeroed → every layer interior; z = L-1
            lay = render_layer(solid, L, cz + 1, config, (), pixel_mm)
            keep = solid.copy() if keep_all else (solid & (lay <= keep_below))  # octet: all interior; else grey-or-darker
            if hull is not None:  # keep only voxels inside the octet primitive at this z
                pts = np.column_stack([grid_xy, np.full(len(grid_xy), float(L - 1))])
                keep &= (hull.find_simplex(pts) >= 0).reshape(cx, cx)
            ys, xs = np.where(keep)
            for y, x in zip(ys.tolist(), xs.tolist()):
                fill.append([x, y, L - 1, int(lay[y, x])])
        return {
            "struts": struts,
            "voxels": fill,
            "cell_mm": [round(cx * pixel_mm, 4), round(cx * length_mm, 4), round(cz * layer_mm, 4)],
            "voxel_size_mm": [round(pixel_mm, 4), round(length_mm, 4), round(layer_mm, 4)],
            "count": len(fill),
        }

    @app.post("/api/calibration/info")
    def calibration_info(req: CalibrationRequest) -> dict:
        config = _config(req.config)
        spec = calibration.build_spec(req.spec or {}, config.printer)
        return {
            "total_layers": calibration.total_layers(spec),
            "resolution": [spec.width_px, spec.height_px],
            "base_layers": spec.base_layers,
            "feature_layers": spec.feature_layers,
        }

    @app.post("/api/calibration/preview")
    def calibration_preview(req: CalibrationRequest) -> Response:
        # "reference" = the LABELED map (RGB) so the layout is legible; "print" = the
        # actual gel-only layer that gets printed (no text). Export ships both.
        config = _config(req.config)
        spec = calibration.build_spec(req.spec or {}, config.printer)
        total = calibration.total_layers(spec)
        buffer = io.BytesIO()
        if req.view == "print":
            index = max(1, min(req.index, total))
            Image.fromarray(calibration.render_calibration_layer(spec, index), mode="L").save(buffer, format="PNG")
            layer_index = str(index)
        else:
            Image.fromarray(calibration.render_reference(spec), mode="RGB").save(buffer, format="PNG")
            layer_index = "1"
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={"X-Total-Layers": str(total), "X-Layer-Index": layer_index},
        )

    @app.post("/api/calibration/export")
    def calibration_export(req: CalibrationRequest) -> FileResponse:
        import dataclasses

        config = _config(req.config)
        spec = calibration.build_spec(req.spec or {}, config.printer)
        total = calibration.total_layers(spec)
        work_dir = tempfile.mkdtemp(prefix="lumengray_calib_")
        try:
            zip_path = os.path.join(work_dir, "calibration.zip")
            pad = max(4, len(str(total)))
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for index in range(1, total + 1):
                    layer = calibration.render_calibration_layer(spec, index)
                    buffer = io.BytesIO()
                    Image.fromarray(layer, mode="L").save(buffer, format="PNG")
                    archive.writestr(f"{index:0{pad}d}.png", buffer.getvalue())
                    del layer, buffer
                manifest = {
                    "generator": "LumenGray calibration chip",
                    "spec": dataclasses.asdict(spec),
                    "answer_key": calibration.answer_key(spec),
                }
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                archive.writestr("measurement.csv", calibration.measurement_csv(spec))
                # Labeled reference map (NOT printed) — the guide for interpreting the
                # gel-only layers when measuring.
                ref_buf = io.BytesIO()
                Image.fromarray(calibration.render_reference(spec), mode="RGB").save(ref_buf, format="PNG")
                archive.writestr("reference.png", ref_buf.getvalue())
        except BaseException:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        gc.collect()
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="LumenX-calibration.zip",
            background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
        )

    @app.post("/api/calibration/voxels")
    def calibration_voxels(req: CalibrationRequest) -> dict:
        """Voxelize the calibration stack for the 3D view: downsampled (x, y, z, value)
        voxels so pyramids/channels are visible in 3D. Bounded voxel count."""
        config = _config(req.config)
        spec = calibration.build_spec(req.spec or {}, config.printer)
        total = calibration.total_layers(spec)
        sample = calibration.render_calibration_layer(spec, min(total, spec.base_layers + 1))
        ys, xs = np.where(sample > 0)
        if xs.size == 0:
            return {"voxels": [], "dims": [0, 0, 0], "count": 0, "truncated": False}
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        cw, ch = x1 - x0, y1 - y0
        f = max(1, round(max(cw, ch, total) / 110))         # ~110 voxels on the longest axis (finer = small features survive)
        nx, ny = cw // f, ch // f
        if nx == 0 or ny == 0:
            return {"voxels": [], "dims": [0, 0, 0], "count": 0, "truncated": False}
        voxels: list = []
        truncated = False
        nz = 0
        for zi in range(0, total, f):
            lay = calibration.render_calibration_layer(spec, zi + 1)[y0:y0 + ny * f, x0:x0 + nx * f]
            block = lay.reshape(ny, f, nx, f).max(axis=(1, 3))   # peak value per block
            rr, cc = np.where(block > 0)
            for r, c in zip(rr.tolist(), cc.tolist()):
                voxels.append([int(c), int(ny - 1 - r), nz, int(block[r, c])])
            nz += 1
            if len(voxels) > 300000:
                truncated = True
                break
        gc.collect()
        return {"voxels": voxels, "dims": [nx, ny, nz], "count": len(voxels), "truncated": truncated}

    @app.post("/api/printability-check")
    def printability_check(req: PrintCheckRequest, session: str = Depends(_session)) -> dict:
        """Phase 3 (flagging only — mutates NOTHING): sample the loaded design's
        photostack and detect solid features thinner than min_pillar and voids
        narrower than min_channel, via morphological opening. Reports counts per
        category so the UI can warn and ask permission before any fix."""
        item = _get(req.id, session)
        config = _config(req.config)
        limits = req.limits or {}
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        px_um = config.printer.voxel_width_um
        pixel_mm = px_um / 1000.0
        regions = resolve_regions(config, canvas_origin(mesh, config.printer, config.center_xy))
        mp, mc = limits.get("min_pillar_um"), limits.get("min_channel_um")
        r_p = max(1, round((mp / px_um) / 2)) if mp else 0
        r_c = max(1, round((mc / px_um) / 2)) if mc else 0

        def disk(r):
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
            return (xx * xx + yy * yy) <= r * r

        thin_solid = solid_total = thin_void = void_total = layers = 0
        for i0 in sample_indices(total, min(max(1, req.samples), total)):
            idx = i0 + 1
            sld = slice_index(mesh, config.printer, config.center_xy, idx)
            lay = render_layer(sld, idx, total, config, regions, pixel_mm)
            solid = lay > 0
            solid_total += int(solid.sum())
            if r_p:
                opened = ndimage.binary_opening(solid, structure=disk(r_p))
                thin_solid += int((solid & ~opened).sum())
            void = sld & (lay < 64)              # carved lumen within the body
            void_total += int(void.sum())
            if r_c and void.any():
                opened_v = ndimage.binary_opening(void, structure=disk(r_c))
                thin_void += int((void & ~opened_v).sum())
            layers += 1
        gc.collect()
        # Flag a category only when a MEANINGFUL fraction is thin (>=1%). Opening a
        # solid convex shape leaves tiny corner slivers (~0%) that aren't real thin
        # features — the threshold rejects those.
        FLAG_PCT = 1.0
        out: dict = {"layers_checked": layers}
        if mp:
            pct = round(100 * thin_solid / max(1, solid_total), 1)
            out["pillar"] = {"limit_um": mp, "below": pct >= FLAG_PCT, "thin_px": thin_solid,
                             "solid_px": solid_total, "pct": pct}
        if mc:
            pct = round(100 * thin_void / max(1, void_total), 1)
            out["channel"] = {"limit_um": mc, "below": pct >= FLAG_PCT, "thin_px": thin_void,
                              "void_px": void_total, "pct": pct}
        return out

    @app.post("/api/calibration/steps")
    def calibration_steps(req: CalibrationRequest) -> dict:
        config = _config(req.config)
        spec = calibration.build_spec(req.spec or {}, config.printer)
        return {"steps": calibration.measurement_steps(spec)}

    @app.post("/api/calibration/solve")
    def calibration_solve_endpoint(req: SolveRequest) -> dict:
        """Phase 2: given the assumed pitch + the filled measurement.csv, fit the true
        XY pitch, the gray→bloom curve, cure threshold, and resolution limit."""
        config = _config(req.config)
        try:
            rows = calibration_solve.parse_measurements(req.csv or "")
        except Exception as error:  # noqa: BLE001 - surface a bad CSV as 400
            raise HTTPException(400, f"Could not parse the measurement CSV: {error}") from error
        answer_key = {"pitch_um": [config.printer.voxel_width_um, config.printer.voxel_length_um]}
        return calibration_solve.solve(answer_key, rows)

    @app.get("/api/check-update")
    def check_update() -> dict:
        """Compare the running version to the latest GitHub release. Read-only: it
        does NOT modify the app — the UI offers a download link and the user runs the
        installer. Fails soft when offline."""
        from .. import __version__

        try:
            # Verify TLS against certifi's CA bundle — a frozen PyInstaller app has no
            # system cert path, so the default context would fail cert verification.
            import ssl

            try:
                import certifi

                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
            req = urllib.request.Request(
                RELEASES_LATEST_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "LumenGray"},
            )
            with urllib.request.urlopen(req, timeout=6, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "current": __version__, "error": "Couldn't reach GitHub — check your connection."}
        latest = (data.get("tag_name") or "").lstrip("vV")
        return {
            "ok": True,
            "current": __version__,
            "latest": latest,
            "update_available": bool(latest) and _version_tuple(latest) > _version_tuple(__version__),
            "releases_url": data.get("html_url") or RELEASES_PAGE,
            "windows_installer_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/LumenGray-Setup.exe",
            "notes": data.get("body") or "",
        }

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


class _BoundedSampler:
    """Collect rows while capping peak memory to ~2x ``limit``.

    Holding every cell/voxel before striking it down to ``limit`` is what spikes
    RAM on large models (millions of tiny lists). This keeps an evenly-strided
    sample in bounded memory and the exact total count, matching the result of
    striding the full list at the end.
    """

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.total = 0
        self.stride = 1
        self.items: list = []

    def add(self, row) -> None:
        if self.total % self.stride == 0:
            self.items.append(row)
            if len(self.items) > 2 * self.limit:
                self.items = self.items[::2]
                self.stride *= 2
        self.total += 1

    def result(self) -> list:
        if len(self.items) > self.limit:
            return self.items[:: -(-len(self.items) // self.limit)]
        return self.items


def _footprint_box(mesh, config) -> tuple[int, int, int, int]:
    """Model XY footprint in output pixels (from mesh bounds) — used to crop the
    canvas so we never allocate/scan the full empty build area."""
    pixel_mm = config.printer.voxel_width_um / 1000.0
    width, height = config.printer.resolution
    origin = canvas_origin(mesh, config.printer, config.center_xy)
    (xmin, ymin) = mesh.bounds[0][:2]
    (xmax, ymax) = mesh.bounds[1][:2]
    to_col = lambda x: (x - origin[0]) / pixel_mm
    to_row = lambda y: (height - 1) - (y - origin[1]) / pixel_mm
    x0 = max(0, int(np.floor(to_col(xmin))))
    x1 = min(width, int(np.ceil(to_col(xmax))) + 1)
    y0 = max(0, int(np.floor(min(to_row(ymin), to_row(ymax)))))
    y1 = min(height, int(np.ceil(max(to_row(ymin), to_row(ymax)))) + 1)
    return x0, y0, x1, y1


app = create_app()
