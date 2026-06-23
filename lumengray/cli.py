"""Command-line entry point for the LumenGray photostack pipeline."""

from __future__ import annotations

import argparse
import sys

from .config import (
    ConfigError,
    Gradient,
    default_config,
    default_tessellation,
    load_config,
)
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lumengray",
        description="Slice an STL into a grayscale photostack for the Lumen X3 "
        "(replaces protocol steps 1-3: Chitubox config, slice/export, ImageJ grayscale).",
    )
    parser.add_argument("stl", help="path to the input .stl model")
    parser.add_argument("-c", "--config", help="path to a JSON config (printer + grayscale regions)")
    parser.add_argument("-o", "--out", default="./photomasks", help="output folder for PNG masks")
    parser.add_argument("--prefix", default="", help="filename prefix for output PNGs")
    parser.add_argument(
        "--layer-height-um",
        type=float,
        help="override layer height in microns (20 / 50 / 100)",
    )
    parser.add_argument(
        "--falloff-mm",
        type=float,
        help="override the edge_feather gradient falloff (mm); enables a default "
        "gradient if the config has none",
    )
    parser.add_argument(
        "--cubic-tessellation",
        action="store_true",
        help="hollow-cube infill mode (white shell, grey core) with white caps and "
        "a per-layer white boundary rim; uses defaults unless a config supplies them",
    )
    parser.add_argument(
        "--grey-value",
        type=int,
        help="grey value (0-255) for the cube core under --cubic-tessellation",
    )
    parser.add_argument("--rotate-x", type=float, help="rotate model degrees about X before slicing")
    parser.add_argument("--rotate-y", type=float, help="rotate model degrees about Y before slicing")
    parser.add_argument("--rotate-z", type=float, help="rotate model degrees about Z before slicing")
    parser.add_argument(
        "--preview",
        action="store_true",
        help=f"also write a contact-sheet thumbnail grid ({{out}}/_preview.png)",
    )
    parser.add_argument("--preview-cols", type=int, default=8, help="preview grid columns")
    parser.add_argument("--preview-tiles", type=int, default=48, help="max layers in the preview")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config) if args.config else default_config()
        if args.layer_height_um is not None:
            config = _override_layer_height(config, args.layer_height_um)
        if args.falloff_mm is not None:
            config = _override_falloff(config, args.falloff_mm)
        config = _override_tessellation(config, args.cubic_tessellation, args.grey_value)
        config = _override_rotation(config, args.rotate_x, args.rotate_y, args.rotate_z)
        summary = run(
            args.stl,
            args.out,
            config,
            name_prefix=args.prefix,
            preview=args.preview,
            preview_cols=args.preview_cols,
            preview_tiles=args.preview_tiles,
        )
    except (ConfigError, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Wrote {summary['layers']} masks to {summary['out_dir']} "
        f"({summary['resolution'][0]}x{summary['resolution'][1]} @ "
        f"{summary['pixel_size_um']}um XY, {summary['layer_height_um']}um Z, "
        f"{summary['regions']} grayscale region(s))"
    )
    if summary["mode"] == "cubic_tessellation":
        tess = config.tessellation
        print(
            f"Mode: cubic_tessellation (cube {tess.cube_xy_px}x{tess.cube_xy_px} px XY "
            f"x {tess.cube_z_layers} layers Z, {tess.shell_px}px shell, "
            f"grey {tess.grey_value}, caps {tess.cap_bottom_layers}/{tess.cap_top_layers}, "
            f"boundary {tess.boundary_um:g}um)"
        )
    if any(summary["rotation_deg"]):
        print(f"Rotation (deg, xyz): {summary['rotation_deg']}")
    if "preview" in summary:
        print(f"Preview: {summary['preview']}")
    return 0


def _override_layer_height(config, layer_height_um):
    from dataclasses import replace

    printer = replace(config.printer, layer_height_um=float(layer_height_um))
    return replace(config, printer=printer)


def _override_falloff(config, falloff_mm):
    from dataclasses import replace

    if falloff_mm <= 0:
        raise ConfigError("--falloff-mm must be positive")
    gradient = config.gradient or Gradient("edge_feather", 40, 255, falloff_mm)
    gradient = replace(gradient, falloff_mm=float(falloff_mm))
    return replace(config, gradient=gradient)


def _override_tessellation(config, enable, grey_value):
    from dataclasses import replace

    tessellation = config.tessellation
    if enable and tessellation is None:
        tessellation = default_tessellation()
    if grey_value is not None:
        if tessellation is None:
            raise ConfigError("--grey-value requires --cubic-tessellation (or a config that enables it)")
        if not 0 <= grey_value <= 255:
            raise ConfigError("--grey-value must be an integer 0-255")
        tessellation = replace(tessellation, grey_value=grey_value)
    if tessellation is config.tessellation:
        return config
    return replace(config, tessellation=tessellation)


def _override_rotation(config, rx, ry, rz):
    from dataclasses import replace

    if rx is None and ry is None and rz is None:
        return config
    current = config.rotation_deg
    updated = (
        float(rx) if rx is not None else current[0],
        float(ry) if ry is not None else current[1],
        float(rz) if rz is not None else current[2],
    )
    return replace(config, rotation_deg=updated)


if __name__ == "__main__":
    raise SystemExit(main())
