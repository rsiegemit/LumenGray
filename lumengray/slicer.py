"""STL -> binary slice masks.

Replaces protocol step 2 (Chitubox slice + export). Each layer is rasterized
onto a fixed canvas with a shared world-space origin so every mask is
registered to the same XY frame (critical for stacking).
"""

from __future__ import annotations

import numpy as np
import trimesh

from .config import Printer


def load_mesh(stl_path: str) -> trimesh.Trimesh:
    mesh = trimesh.load(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
        raise ValueError(f"Could not load a mesh from {stl_path}")
    if not mesh.is_watertight:
        print("[slicer] warning: mesh is not watertight; filled slices may be inaccurate")
    return mesh


def orient_mesh(mesh: trimesh.Trimesh, rotation_deg: tuple) -> trimesh.Trimesh:
    """Rotate the mesh (degrees, X->Y->Z) about its bounding-box center before slicing."""
    if not any(rotation_deg):
        return mesh
    transforms = trimesh.transformations
    rx, ry, rz = np.radians(rotation_deg)
    rotation = transforms.euler_matrix(rx, ry, rz, axes="sxyz")
    center = mesh.bounds.mean(axis=0)
    matrix = transforms.translation_matrix(center) @ rotation @ transforms.translation_matrix(-center)
    mesh.apply_transform(matrix)
    return mesh


def slice_mesh(mesh: trimesh.Trimesh, printer: Printer, center_xy: bool) -> list[np.ndarray]:
    """Return a list of boolean (height, width) masks, bottom layer first.

    True = solid (cured) pixel. Empty layers yield an all-False mask so the
    stack ordering stays contiguous.
    """
    pixel_mm = printer.voxel_width_um / 1000.0  # square XY pitch (width == length)
    layer_mm = printer.voxel_height_um / 1000.0
    width, height = printer.resolution

    z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    origin_xy = canvas_origin(mesh, printer, center_xy)
    _warn_if_oversized(mesh, printer)

    masks: list[np.ndarray] = []
    z = z_min + layer_mm / 2.0
    while z < z_max:
        masks.append(_rasterize_layer(mesh, z, origin_xy, pixel_mm, (width, height)))
        z += layer_mm
    return masks


def layer_z_values(mesh: trimesh.Trimesh, printer: Printer) -> list[float]:
    """World-space Z (mm) of every slice plane, bottom first - the stack's layer count."""
    layer_mm = printer.voxel_height_um / 1000.0
    z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    values: list[float] = []
    z = z_min + layer_mm / 2.0
    while z < z_max:
        values.append(z)
        z += layer_mm
    return values


def count_layers(mesh: trimesh.Trimesh, printer: Printer) -> int:
    return len(layer_z_values(mesh, printer))


def slice_index(mesh: trimesh.Trimesh, printer: Printer, center_xy: bool, index: int) -> np.ndarray:
    """Rasterize a single layer (1-indexed) without slicing the whole stack."""
    zs = layer_z_values(mesh, printer)
    if not 1 <= index <= len(zs):
        raise ValueError(f"layer index {index} out of range 1..{len(zs)}")
    pixel_mm = printer.voxel_width_um / 1000.0  # square XY pitch (width == length)
    width, height = printer.resolution
    origin_xy = canvas_origin(mesh, printer, center_xy)
    return _rasterize_layer(mesh, zs[index - 1], origin_xy, pixel_mm, (width, height))


def _rasterize_layer(mesh, z, origin_xy, pixel_mm, resolution) -> np.ndarray:
    width, height = resolution
    section = mesh.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
    if section is None:
        return np.zeros((height, width), dtype=bool)
    # plane_transform for a +Z plane preserves world (x, y) in the 2D frame,
    # so a fixed world-space origin keeps every layer registered.
    to_2d = trimesh.geometry.plane_transform(origin=[0.0, 0.0, z], normal=[0.0, 0.0, 1.0])
    planar, _ = section.to_planar(to_2D=to_2d)
    image = planar.rasterize(
        pitch=pixel_mm,
        origin=origin_xy,
        resolution=(width, height),
        fill=True,
    )
    # PIL row 0 is top; flip so world +Y points up across the whole stack.
    return np.flipud(np.array(image, dtype=bool))


def canvas_origin(mesh, printer: Printer, center_xy: bool) -> np.ndarray:
    """World-space (mm) lower-left corner of the raster canvas, shared by all layers."""
    pixel_mm = printer.voxel_width_um / 1000.0  # square XY pitch (width == length)
    width, height = printer.resolution
    canvas_mm = np.array([width * pixel_mm, height * pixel_mm])
    if center_xy:
        model_center = (mesh.bounds[0][:2] + mesh.bounds[1][:2]) / 2.0
        return model_center - canvas_mm / 2.0
    return np.array(mesh.bounds[0][:2], dtype=float)


def _warn_if_oversized(mesh, printer: Printer) -> None:
    pixel_mm = printer.voxel_width_um / 1000.0  # square XY pitch (width == length)
    width, height = printer.resolution
    canvas_mm = np.array([width * pixel_mm, height * pixel_mm])
    model_mm = mesh.bounds[1][:2] - mesh.bounds[0][:2]
    if (model_mm > canvas_mm).any():
        print(
            f"[slicer] warning: model XY {model_mm.round(2)} mm exceeds build area "
            f"{canvas_mm.round(2)} mm; it will be clipped"
        )
