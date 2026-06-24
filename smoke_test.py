"""End-to-end smoke test: generate an STL, run the pipeline, assert outputs."""

import os
import tempfile

import numpy as np
import trimesh
from PIL import Image

from lumengray.config import default_config, default_tessellation, load_config
from lumengray.pipeline import run


def main():
    work = tempfile.mkdtemp(prefix="lumen_smoke_")
    stl_path = os.path.join(work, "block.stl")

    # 30 x 20 x 5 mm block, centered on the XY origin.
    box = trimesh.creation.box(extents=[30.0, 20.0, 5.0])
    box.export(stl_path)

    # --- default config: uniform white masks ---
    out_uniform = os.path.join(work, "uniform")
    summary = run(stl_path, out_uniform, default_config())
    expected = int(5.0 / (50 / 1000.0))  # 5mm / 50um = 100 layers
    files = sorted(os.listdir(out_uniform))
    assert summary["layers"] == expected, (summary["layers"], expected)
    assert len(files) == expected, len(files)

    img = np.array(Image.open(os.path.join(out_uniform, files[0])))
    assert img.shape == (1080, 1920), img.shape
    solid_px = int((img == 255).sum())
    # 30x20mm at 35um pixel -> ~ (30/0.035)*(20/0.035) ~ 489795 px
    expected_px = (30 / 0.035) * (20 / 0.035)
    assert abs(solid_px - expected_px) / expected_px < 0.02, (solid_px, expected_px)
    assert set(np.unique(img)).issubset({0, 255}), np.unique(img)

    # --- config with grayscale regions ---
    cfg = load_config(os.path.join(os.path.dirname(__file__), "config.example.json"))
    out_gray = os.path.join(work, "gray")
    summary = run(stl_path, out_gray, cfg, preview=True)
    gray_files = [f for f in sorted(os.listdir(out_gray)) if f != "_preview.png"]

    # Layer 1 (in [1,20]) should contain the dim rect (128) and circle (80).
    layer1 = np.array(Image.open(os.path.join(out_gray, gray_files[0])))
    vals1 = set(np.unique(layer1).tolist())
    assert 128 in vals1, vals1
    assert 80 in vals1, vals1
    assert 200 in vals1, vals1  # mm-unit region landed
    assert 180 not in vals1, vals1  # polygon is top-layers only

    # A top layer (index > 20) should contain the polygon (180), not the rect.
    # The polygon is listed after the circle and overlaps it, so by region
    # precedence (later wins) it overwrites the circle here.
    layer_top = np.array(Image.open(os.path.join(out_gray, gray_files[50])))
    vals_top = set(np.unique(layer_top).tolist())
    assert 180 in vals_top, vals_top
    assert 128 not in vals_top, vals_top  # rect is lower-layers only

    # clip_to_solid: no region value may appear outside the cured area.
    block_mask = np.array(Image.open(os.path.join(out_uniform, files[50]))) == 255
    assert not (layer_top != 0)[~block_mask].any(), "grayscale leaked outside solid"

    # mm conversion lands where the math predicts: world (-12, 6) mm, 35um pixel,
    # origin (-33.6, -14.9) -> col ~617, row ~368 (Y inverted).
    ys, xs = np.where(layer1 == 200)
    cx, cy = xs.mean(), ys.mean()
    assert abs(cx - 617) < 4 and abs(cy - 368) < 4, (cx, cy)

    # preview contact sheet was written and is a real image.
    assert "preview" in summary and os.path.exists(summary["preview"])
    sheet = Image.open(summary["preview"])
    assert sheet.width > 0 and sheet.height > 0, sheet.size

    # --- edge-feather gradient: dark at edges, bright in the core ---
    grad_cfg = load_config(os.path.join(os.path.dirname(__file__), "config.tube.json"))
    out_grad = os.path.join(work, "grad")
    run(stl_path, out_grad, grad_cfg)
    glayer = np.array(Image.open(os.path.join(out_grad, sorted(os.listdir(out_grad))[50])))
    block = np.array(Image.open(os.path.join(out_uniform, files[50]))) == 255
    solid_vals = glayer[block]
    assert solid_vals.min() >= 40, solid_vals.min()  # never below the floor
    assert solid_vals.max() == 255, solid_vals.max()  # core reaches full brightness
    assert not (glayer != 0)[~block].any(), "gradient leaked outside solid"
    # the block center is brighter than an edge column.
    mid_row = glayer.shape[0] // 2
    edge_col = np.where(block[mid_row])[0][0]  # first solid pixel in that row
    assert glayer[mid_row, glayer.shape[1] // 2] > glayer[mid_row, edge_col], "edge not darker"

    # --- rotation: 90deg about Y swaps the 30mm X-extent into Z (5mm -> 30mm tall) ---
    from dataclasses import replace

    rot_cfg = replace(default_config(), rotation_deg=(0.0, 90.0, 0.0))
    out_rot = os.path.join(work, "rot")
    rot_summary = run(stl_path, out_rot, rot_cfg)
    assert rot_summary["layers"] == int(round(30.0 / (50 / 1000.0))), rot_summary["layers"]  # 600
    rimg = np.array(Image.open(os.path.join(out_rot, sorted(os.listdir(out_rot))[300])))
    assert rimg.shape == (1080, 1920), rimg.shape

    # --- cubic tessellation: white caps, edge-strut infill, white boundary rim ---
    from dataclasses import replace as _replace

    # 7x10x4mm prism -> 4mm/50um = 80 layers (2 bottom caps + 76 middle + 2 top caps).
    prism_path = os.path.join(work, "prism.stl")
    trimesh.creation.box(extents=[7.0, 10.0, 4.0]).export(prism_path)
    tess = default_tessellation()
    out_tess = os.path.join(work, "tess")
    tsum = run(prism_path, out_tess, _replace(default_config(), tessellation=tess))
    assert tsum["mode"] == "cubic_tessellation", tsum["mode"]
    assert tsum["layers"] == 80, tsum["layers"]
    tfiles = sorted(os.listdir(out_tess))

    def tlayer(i):  # 1-indexed
        return np.array(Image.open(os.path.join(out_tess, tfiles[i - 1])))

    # caps (1,2 and 79,80) are solid white only; no grey.
    for i in (1, 2, 79, 80):
        vals = set(np.unique(tlayer(i)).tolist())
        assert vals.issubset({0, 255}) and 255 in vals, (i, vals)
    # interior + cube-face layers both carry grey now (faces are open frames, not walls).
    assert set(np.unique(tlayer(5)).tolist()) == {0, 128, 255}, np.unique(tlayer(5))
    assert set(np.unique(tlayer(3)).tolist()) == {0, 128, 255}, np.unique(tlayer(3))

    # layer 5 reproduces the exact edge-strut + boundary-rim prediction.
    from scipy import ndimage as _ndi

    L = tlayer(5)
    solid_t = L > 0
    H, W = L.shape
    col_s = (np.arange(W) % tess.cube_xy_px) < tess.shell_px  # shared grid line (low face)
    row_s = (np.arange(H) % tess.cube_xy_px) < tess.shell_px
    # layer 5: z_in_cube=(5-1-2)%6=2 → not a z-grid layer → strut where col-grid AND row-grid.
    strut_t = col_s[None, :] & row_s[:, None]
    pred = np.zeros_like(L)
    pred[solid_t] = np.where(strut_t[solid_t], 255, 128)
    bpx = tess.boundary_px
    rim_t = solid_t & (_ndi.distance_transform_cdt(solid_t, metric="chessboard") <= bpx)
    pred[rim_t] = 255
    assert np.array_equal(pred, L), f"{int((pred != L).sum())} px differ from prediction"

    # struts run continuously up/down; true cores stay grey through every interior layer.
    strut_px = np.argwhere(strut_t & solid_t & ~rim_t)[0]
    core_px = np.argwhere((~col_s[None, :]) & (~row_s[:, None]) & solid_t & ~rim_t)[0]
    strut_col = [int(tlayer(i)[strut_px[0], strut_px[1]]) for i in range(3, 9)]
    core_col = [int(tlayer(i)[core_px[0], core_px[1]]) for i in range(3, 9)]
    assert all(v == 255 for v in strut_col), strut_col
    assert all(v == 128 for v in core_col), core_col

    print("OK:", expected, "layers, dims", img.shape, "| px+mm regions | clip | gradient | rotate->", rot_summary["layers"], "layers | preview", sheet.size)
    print("cubic tessellation:", tsum["layers"], "layers | caps+edge-struts+rim verified | strut", strut_col, "core", core_col)
    print("sample output:", out_gray)


if __name__ == "__main__":
    main()
