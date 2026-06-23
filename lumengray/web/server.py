"""FastAPI backend for LumenGray.

Thin HTTP layer over ``lumengray``: upload an STL, preview any single layer
live as parameters change, and export the full grayscale photostack as a zip.
All slicing/grayscale logic lives in the library; this module only wires it to
HTTP and keeps uploaded meshes warm in memory for fast previews.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass

import numpy as np
import trimesh
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from ..config import ConfigError, config_from_dict
from ..pipeline import render_layer, resolve_regions, run
from ..preview import sample_indices
from ..slicer import canvas_origin, count_layers, load_mesh, orient_mesh, slice_index
from .presets import PRESETS, build_preset_mesh, get_preset, mode_of

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


@dataclass
class Upload:
    path: str
    name: str
    mesh: trimesh.Trimesh


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


class LatticeRequest(BaseModel):
    id: str
    config: dict
    max_cells: int = 40000


def create_app() -> FastAPI:
    app = FastAPI(title="LumenGray", version="0.1.0")
    uploads: dict[str, Upload] = {}
    upload_dir = tempfile.mkdtemp(prefix="lumengray_uploads_")

    @app.middleware("http")
    async def _no_cache(request, call_next):
        # Local tool: never let the browser serve stale UI assets.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _get(upload_id: str) -> Upload:
        item = uploads.get(upload_id)
        if item is None:
            raise HTTPException(404, "Unknown model id - upload an STL first")
        return item

    def _config(raw: dict):
        try:
            return config_from_dict(raw)
        except ConfigError as error:
            raise HTTPException(400, str(error)) from error

    def _oriented(item: Upload, config) -> trimesh.Trimesh:
        # orient_mesh mutates in place, so always work on a copy of the cached mesh.
        return orient_mesh(item.mesh.copy(), config.rotation_deg)

    def _register(mesh: trimesh.Trimesh, name: str) -> dict:
        upload_id = uuid.uuid4().hex
        path = os.path.join(upload_dir, f"{upload_id}.stl")
        mesh.export(path)
        uploads[upload_id] = Upload(path=path, name=name, mesh=mesh)
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
    async def upload(file: UploadFile) -> dict:
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
        return _register(mesh, file.filename or "model.stl")

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
                    "extents_mm": [round(v, 1) for v in extents],
                    "mode": mode_of(preset["config"]),
                }
            )
        return out

    @app.post("/api/preset/{preset_id}")
    def load_preset(preset_id: str) -> dict:
        preset = get_preset(preset_id)
        if preset is None:
            raise HTTPException(404, "Unknown preset")
        result = _register(build_preset_mesh(preset_id), f"{preset['name']}.stl")
        result["config"] = preset["config"]
        return result

    @app.get("/api/model/{upload_id}")
    def model(upload_id: str) -> FileResponse:
        item = _get(upload_id)
        return FileResponse(item.path, media_type="model/stl", filename=item.name)

    @app.post("/api/info")
    def info(req: InfoRequest) -> dict:
        item = _get(req.id)
        config = _config(req.config)
        mesh = _oriented(item, config)
        extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()
        return {
            "total_layers": count_layers(mesh, config.printer),
            "resolution": list(config.printer.resolution),
            "extents_mm": [round(v, 3) for v in extents],
            "mode": "cubic_tessellation" if config.tessellation is not None else "regions",
        }

    @app.post("/api/preview")
    def preview(req: PreviewRequest) -> Response:
        item = _get(req.id)
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
        pixel_mm = config.printer.pixel_size_um / 1000.0
        layer = render_layer(solid, index, total, config, regions, pixel_mm)
        buffer = io.BytesIO()
        Image.fromarray(layer, mode="L").save(buffer, format="PNG")
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={"X-Total-Layers": str(total), "X-Layer-Index": str(index)},
        )

    @app.post("/api/export")
    def export(req: ExportRequest) -> StreamingResponse:
        item = _get(req.id)
        config = _config(req.config)
        out_dir = tempfile.mkdtemp(prefix="lumengray_export_")
        try:
            summary = run(item.path, out_dir, config, name_prefix=req.prefix)
        except (ValueError, ConfigError) as error:
            raise HTTPException(400, str(error)) from error
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename in sorted(os.listdir(out_dir)):
                archive.write(os.path.join(out_dir, filename), filename)
            archive.writestr("manifest.json", _manifest(summary, item.name))
        buffer.seek(0)
        stem = os.path.splitext(item.name)[0] or "photostack"
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{stem}_lumengray.zip"'},
        )

    @app.post("/api/stack")
    def stack(req: StackRequest) -> dict:
        item = _get(req.id)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")
        origin = canvas_origin(mesh, config.printer, config.center_xy)
        regions = resolve_regions(config, origin)
        pixel_mm = config.printer.pixel_size_um / 1000.0
        layer_mm = config.printer.layer_height_um / 1000.0

        count = max(1, min(req.max_layers, total))
        rendered = []
        for i0 in sample_indices(total, count):
            idx = i0 + 1
            solid = slice_index(mesh, config.printer, config.center_xy, idx)
            rendered.append((idx, render_layer(solid, idx, total, config, regions, pixel_mm)))

        # Union bounding box of cured pixels across the sampled layers (so the
        # textured planes hug the model instead of the full empty canvas).
        box = None
        for _, layer in rendered:
            ys, xs = np.where(layer > 0)
            if xs.size:
                b = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                box = b if box is None else [min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3])]
        if box is None:
            raise HTTPException(400, "Model produced only empty layers")
        x0, y0, x1, y1 = box
        crop_w, crop_h = x1 - x0, y1 - y0
        scale = min(1.0, req.max_px / max(crop_w, crop_h))
        out_w, out_h = max(1, round(crop_w * scale)), max(1, round(crop_h * scale))

        layers = []
        for idx, layer in rendered:
            crop = layer[y0:y1, x0:x1]
            # gray RGB; alpha = gray so background is transparent and the grey
            # cores read as semi-transparent while white shells stay opaque.
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
        return {
            "count": len(layers),
            "total_layers": total,
            "plane_w_mm": round(crop_w * pixel_mm, 4),
            "plane_h_mm": round(crop_h * pixel_mm, 4),
            "height_mm": round(total * layer_mm, 4),
            "layers": layers,
        }

    @app.post("/api/voxels")
    def voxels(req: VoxelRequest) -> dict:
        item = _get(req.id)
        config = _config(req.config)
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")

        pixel_mm = config.printer.pixel_size_um / 1000.0
        layer_mm = config.printer.layer_height_um / 1000.0
        width, height = config.printer.resolution
        origin = canvas_origin(mesh, config.printer, config.center_xy)
        regions = resolve_regions(config, origin)

        # Model XY footprint in pixels (from mesh bounds) so we don't voxelize empty canvas.
        (xmin, ymin) = mesh.bounds[0][:2]
        (xmax, ymax) = mesh.bounds[1][:2]
        to_col = lambda x: (x - origin[0]) / pixel_mm
        to_row = lambda y: (height - 1) - (y - origin[1]) / pixel_mm
        c0 = max(0, int(np.floor(to_col(xmin))))
        c1 = min(width, int(np.ceil(to_col(xmax))) + 1)
        r0 = max(0, int(np.floor(min(to_row(ymin), to_row(ymax)))))
        r1 = min(height, int(np.ceil(max(to_row(ymin), to_row(ymax)))) + 1)
        if c1 <= c0 or r1 <= r0:
            raise HTTPException(400, "Model footprint is outside the build area")
        crop_w, crop_h = c1 - c0, r1 - r0

        height_mm = total * layer_mm
        max_dim_mm = max(crop_w * pixel_mm, crop_h * pixel_mm, height_mm)
        voxel_mm = max(max_dim_mm / max(8, req.target), pixel_mm)
        fxy = max(1, round(voxel_mm / pixel_mm))
        fz = max(1, round(voxel_mm / layer_mm))
        ncx, ncy, nz = -(-crop_w // fxy), -(-crop_h // fxy), -(-total // fz)

        out: list[list[float]] = []
        for kz in range(nz):
            idx = min(total, kz * fz + fz // 2 + 1)  # center layer of the slab → fills the height
            layer = render_layer(slice_index(mesh, config.printer, config.center_xy, idx), idx, total, config, regions, pixel_mm)
            crop = layer[r0:r1, c0:c1].astype(np.float32)
            padded = np.zeros((ncy * fxy, ncx * fxy), dtype=np.float32)
            padded[:crop_h, :crop_w] = crop
            blocks = padded.reshape(ncy, fxy, ncx, fxy)
            solid = blocks > 0
            count = solid.sum(axis=(1, 3))
            mean = np.where(count > 0, blocks.sum(axis=(1, 3)) / np.maximum(count, 1), 0)
            z_mm = (kz * fz + fz / 2.0) * layer_mm
            for cy, cx in zip(*np.where(count > 0)):
                x_mm = (c0 + cx * fxy + fxy / 2.0) * pixel_mm
                y_mm = (height - 1 - (r0 + cy * fxy + fxy / 2.0)) * pixel_mm
                out.append([round(float(x_mm), 3), round(float(y_mm), 3), round(float(z_mm), 3), int(mean[cy, cx])])

        truncated = len(out) > req.max_voxels
        if truncated:
            out = out[:: -(-len(out) // req.max_voxels)]
        return {
            "voxel_size_mm": [round(fxy * pixel_mm, 4), round(fxy * pixel_mm, 4), round(fz * layer_mm, 4)],
            "voxels": out,
            "count": len(out),
            "truncated": truncated,
            "height_mm": round(height_mm, 4),
        }

    @app.post("/api/lattice")
    def lattice(req: LatticeRequest) -> dict:
        item = _get(req.id)
        config = _config(req.config)
        if config.tessellation is None:
            raise HTTPException(400, "Lattice view requires cubic tessellation mode")
        t = config.tessellation
        mesh = _oriented(item, config)
        total = count_layers(mesh, config.printer)
        if total == 0:
            raise HTTPException(400, "No layers produced; check layer height vs model Z extent")

        pixel_mm = config.printer.pixel_size_um / 1000.0
        layer_mm = config.printer.layer_height_um / 1000.0
        cube_xy, cube_z = t.cube_xy_px, t.cube_z_layers
        first, last = t.cap_bottom_layers + 1, total - t.cap_top_layers

        cells: list[list[float]] = []
        # One representative slice per Z-band gives that band's XY cube occupancy.
        band_start = first
        while band_start <= last:
            band_end = min(band_start + cube_z - 1, last)
            rep = (band_start + band_end) // 2
            solid = slice_index(mesh, config.printer, config.center_xy, rep)
            height, width = solid.shape
            ncy, ncx = -(-height // cube_xy), -(-width // cube_xy)
            padded = np.zeros((ncy * cube_xy, ncx * cube_xy), dtype=bool)
            padded[:height, :width] = solid
            occupied = padded.reshape(ncy, cube_xy, ncx, cube_xy).any(axis=(1, 3))
            z_mm = ((band_start + band_end) / 2.0 - 0.5) * layer_mm
            for cy, cx in zip(*np.where(occupied)):
                col_c = cx * cube_xy + cube_xy / 2.0
                row_c = cy * cube_xy + cube_xy / 2.0
                cells.append([
                    round(float(col_c * pixel_mm), 4),
                    round(float((height - 1 - row_c) * pixel_mm), 4),
                    round(float(z_mm), 4),
                ])
            band_start += cube_z

        total_cells = len(cells)
        truncated = total_cells > req.max_cells
        if truncated:
            cells = cells[:: -(-total_cells // req.max_cells)]
        return {
            "cube_size_mm": [round(cube_xy * pixel_mm, 4), round(cube_xy * pixel_mm, 4), round(cube_z * layer_mm, 4)],
            "cells": cells,
            "count": total_cells,
            "truncated": truncated,
            "height_mm": round(total * layer_mm, 4),
        }

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _manifest(summary: dict, source_name: str) -> str:
    import json

    return json.dumps(
        {
            "generator": "LumenGray",
            "source": source_name,
            "layers": summary["layers"],
            "resolution": list(summary["resolution"]),
            "layer_height_um": summary["layer_height_um"],
            "pixel_size_um": summary["pixel_size_um"],
            "mode": summary["mode"],
        },
        indent=2,
    )


app = create_app()
