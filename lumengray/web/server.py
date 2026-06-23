"""FastAPI backend for LumenGray.

Thin HTTP layer over ``lumengray``: upload an STL, preview any single layer
live as parameters change, and export the full grayscale photostack as a zip.
All slicing/grayscale logic lives in the library; this module only wires it to
HTTP and keeps uploaded meshes warm in memory for fast previews.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass

import trimesh
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from ..config import ConfigError, config_from_dict
from ..pipeline import render_layer, resolve_regions, run
from ..slicer import canvas_origin, count_layers, load_mesh, orient_mesh, slice_index

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


def create_app() -> FastAPI:
    app = FastAPI(title="LumenGray", version="0.1.0")
    uploads: dict[str, Upload] = {}
    upload_dir = tempfile.mkdtemp(prefix="lumengray_uploads_")

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
        upload_id = uuid.uuid4().hex
        path = os.path.join(upload_dir, f"{upload_id}.stl")
        with open(path, "wb") as handle:
            handle.write(data)
        try:
            mesh = load_mesh(path)
        except Exception as error:  # noqa: BLE001 - surface any STL load failure as 400
            os.remove(path)
            raise HTTPException(400, f"Could not read STL: {error}") from error
        uploads[upload_id] = Upload(path=path, name=file.filename or "model.stl", mesh=mesh)
        extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()
        return {
            "id": upload_id,
            "name": file.filename,
            "extents_mm": [round(v, 3) for v in extents],
            "watertight": bool(mesh.is_watertight),
            "triangles": int(len(mesh.faces)),
        }

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
