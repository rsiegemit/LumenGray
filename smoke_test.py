"""End-to-end smoke test: generate an STL, run the pipeline, assert outputs."""

import json
import os
import tempfile

import numpy as np
import trimesh
from PIL import Image

from lumengray.config import default_config, default_tessellation, load_config
from lumengray.pipeline import run, render_layer, stack_basename


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
    files = sorted(f for f in os.listdir(out_uniform) if f.endswith(".png"))
    assert summary["layers"] == expected, (summary["layers"], expected)
    assert len(files) == expected, len(files)
    assert "manifest.json" in os.listdir(out_uniform), "run() should write a manifest"

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
    gray_files = [f for f in sorted(os.listdir(out_gray)) if f.endswith(".png") and f != "_preview.png"]

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

    # --- radial gradient: bright at the centre (255), dark toward the edge (floor 40) ---
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

    # --- triangular tessellation (shares the same base) + black core ---
    from lumengray.config import default_triangular

    tri = _replace(default_triangular(), core_px=3)
    out_tri = os.path.join(work, "tri")
    trisum = run(prism_path, out_tri, _replace(default_config(), triangulation=tri))
    assert trisum["mode"] == "triangular_tessellation", trisum["mode"]
    trifiles = sorted(os.listdir(out_tri))
    # a frame layer (z_in=0 → idx 3) shows the triangular grid (white + grey, no black yet);
    # a z-core interior layer carries the black void cores.
    frame = np.array(Image.open(os.path.join(out_tri, trifiles[2])))  # layer 3
    assert set(np.unique(frame).tolist()) == {0, 128, 255}, np.unique(frame)
    core_layer = np.array(Image.open(os.path.join(out_tri, trifiles[4])))  # layer 5 (z_in=2, core band)
    block = np.array(Image.open(os.path.join(out_tess, tfiles[4]))) > 0  # prism footprint
    interior_black = int(((core_layer == 0) & block).sum())
    assert interior_black > 0, "triangular black core produced no void inside the solid"

    # --- octet truss: sloped struts → values {0,128,255}; struts move in XY layer-to-layer ---
    from lumengray.config import default_octet

    out_oct = os.path.join(work, "oct")
    oct_cfg = _replace(default_octet(), cell_xy_px=20, cell_z_layers=14, core_px=6)
    octsum = run(prism_path, out_oct, _replace(default_config(), octet=oct_cfg))
    assert octsum["mode"] == "octet_tessellation", octsum["mode"]
    assert octsum["name"].endswith("core6"), octsum["name"]  # core is in the parametric name
    octfiles = sorted(f for f in os.listdir(out_oct) if f.endswith(".png"))
    o5 = np.array(Image.open(os.path.join(out_oct, octfiles[4])))  # interior layer
    o6 = np.array(Image.open(os.path.join(out_oct, octfiles[5])))
    assert set(np.unique(o5).tolist()) == {0, 128, 255}, np.unique(o5)
    # sloped struts: the white pattern must shift between adjacent interior layers
    white_moves = int(((o5 == 255) != (o6 == 255)).sum())
    assert white_moves > 0, "octet struts should move in XY between layers (sloped)"
    # octahedral cores: interior black voids that grow/shrink in Z (not the empty exterior)
    pfoot = np.array(Image.open(os.path.join(out_tess, tfiles[4]))) > 0
    oct_black = [int(((np.array(Image.open(os.path.join(out_oct, f))) == 0) & pfoot).sum()) for f in octfiles]
    assert max(oct_black) > 0, "octet core produced no interior void"

    # --- gyroid void-connector overlay: carves a connected void into a solid part ---
    from lumengray.config import default_gyroid
    from scipy import ndimage as _ndi

    out_gy = os.path.join(work, "gy")
    gy_cfg = _replace(default_config(), default_solid_value=255, gyroid=_replace(default_gyroid(), cell_mm=0.7, channel_px=4))
    gysum = run(prism_path, out_gy, gy_cfg)
    assert "gyroid-c0.7-w4" in gysum["name"], gysum["name"]  # overlay in the parametric name
    gyfiles = sorted(f for f in os.listdir(out_gy) if f.endswith(".png"))
    gmid = np.array(Image.open(os.path.join(out_gy, gyfiles[len(gyfiles) // 2])))
    # a uniform-solid prism has NO voids; the gyroid must carve black channels into it,
    # and those channels must form far fewer components than isolated dots (connected).
    gy_black = int((gmid == 0).sum())
    assert gy_black > 0, "gyroid overlay carved no void into the solid part"
    vol = np.stack([np.array(Image.open(os.path.join(out_gy, f))) == 0 for f in gyfiles[20:44]])
    ncomp = int(_ndi.label(vol)[1])
    assert ncomp < gy_black // 50, f"gyroid void not connected: {ncomp} components"
    # skin: the void must not breach the boundary — no black in the outer skin_px ring
    edge = pfoot & ~_ndi.binary_erosion(pfoot, iterations=default_gyroid().skin_px)
    assert not ((gmid == 0) & edge).any(), "gyroid void breached the boundary skin"

    # --- structure->core gradient: grades octet cells white(struts)->black(core) ---
    from lumengray.config import default_grade

    from lumengray.config import Grade

    oct_base = _replace(default_octet(), cell_xy_px=20, cell_z_layers=14, core_px=0, boundary_px=0)
    cont = _replace(default_config(), octet=oct_base, grade=default_grade())  # linear [0,255]->[1,0]
    piece = _replace(default_config(), octet=oct_base, grade=Grade(stops=((0.0, 255), (0.5, 128), (1.0, 0)), interp="step"))
    lc = render_layer(np.ones((60, 60), bool), 7, 40, cont, (), 0.035)
    lp = render_layer(np.ones((60, 60), bool), 7, 40, piece, (), 0.035)
    n_cont = len(np.unique(lc))
    piece_vals = set(np.unique(lp).tolist())
    assert n_cont >= 6, f"continuous grade too flat: {n_cont} values"  # a smooth ramp
    assert piece_vals <= {0, 128, 255}, piece_vals  # stepped ramp: only the stop levels
    assert stack_basename(cont, "x").endswith("grade-lin2"), stack_basename(cont, "x")

    # --- unit-cell void connector (cubic): the tiling path links every core into one net ---
    # (The existing gyroid case is non-periodic; this exercises connect_cell's tiling.)
    cube_solid = np.ones((80, 80), bool)
    cube_core = _replace(
        default_config(), default_solid_value=255,
        tessellation=_replace(default_tessellation(), cube_xy_px=10, cube_z_layers=8, core_px=4, boundary_px=0),
    )
    cube_conn = _replace(cube_core, gyroid=_replace(default_gyroid(), channel_px=2, route="geodesic", skin_px=2))
    span = range(12, 28)
    vol_off = np.stack([render_layer(cube_solid, i, 60, cube_core, (), 0.035) <= 0 for i in span])
    vol_on = np.stack([render_layer(cube_solid, i, 60, cube_conn, (), 0.035) <= 0 for i in span])
    assert vol_off.any(), "cubic cores produced no void to connect"
    n_off = int(_ndi.label(vol_off)[1])
    n_on = int(_ndi.label(vol_on)[1])
    assert n_on < n_off, f"cubic connector didn't merge cores: on={n_on} off={n_off}"
    assert n_on == 1, f"cubic void net not fully connected: {n_on} components (expected 1)"

    # --- manifest / config round trip: to_dict -> from_dict is stable (drives load-to-restore) ---
    from lumengray.config import config_from_dict, config_to_dict

    for rc in (default_config(), cube_core, gy_cfg, cont):
        d1 = config_to_dict(rc)
        assert config_to_dict(config_from_dict(d1)) == d1, "config round trip changed the config"
    with open(os.path.join(out_uniform, "manifest.json")) as fh:
        config_from_dict(json.load(fh))  # a written manifest must load back as a config

    # --- band_px crosslink seam: a stepped grade with band_px lays a white weld the plain step lacks ---
    from lumengray.grade import apply_ramp

    ramp2d = np.tile(np.linspace(0.0, 1.0, 40), (12, 1))
    plain = apply_ramp(ramp2d, ((0.0, 0), (1.0, 200)), "step", band_px=0)
    welded = apply_ramp(ramp2d, ((0.0, 0), (1.0, 200)), "step", band_px=2)
    assert set(np.unique(plain).tolist()) <= {0.0, 200.0}, np.unique(plain)  # plain step: only stop levels
    assert int((welded == 255).sum()) > int((plain == 255).sum()), "band_px added no white seam"

    # --- apply_min_feature: byte-for-byte no-op (same object) when nothing qualifies ---
    from lumengray.min_feature import apply_min_feature

    solid_block = np.full((50, 50), 255, np.uint8)
    everywhere = np.ones((50, 50), bool)
    assert apply_min_feature(solid_block, everywhere) is solid_block  # nothing enabled
    assert apply_min_feature(solid_block, everywhere, min_pillar_px=6, fix_pillar=True) is solid_block  # solid: no thin

    print("OK:", expected, "layers, dims", img.shape, "| px+mm regions | clip | gradient | rotate->", rot_summary["layers"], "layers | preview", sheet.size)
    print("regression guards: cubic connector components on/off", n_on, "/", n_off, "| config round trip | band_px seam | min_feature no-op")
    print("triangular tessellation:", trisum["layers"], "layers | grid+struts+black-core verified | interior void px", interior_black)
    print("octet truss:", octsum["layers"], "layers | values {0,128,255} | sloped-strut XY shift px", white_moves, "| octahedral core max-void px", max(oct_black))
    print("gyroid connector:", gysum["layers"], "layers | carved void px/layer", gy_black, "| connected components", ncomp)
    print("cubic tessellation:", tsum["layers"], "layers | caps+edge-struts+rim verified | strut", strut_col, "core", core_col)
    print("sample output:", out_gray)


if __name__ == "__main__":
    main()
