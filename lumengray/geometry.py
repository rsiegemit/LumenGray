"""Convert mm (world/model) shapes into output-PNG pixel shapes.

World axes follow the slicer: +X is right, +Y is up. The raster has row 0 at
the top, so Y is inverted when mapping to pixels:
    col = (x_mm - origin_x) / pixel_mm
    row = (height - 1) - (y_mm - origin_y) / pixel_mm
"""

from __future__ import annotations


def shape_to_pixels(shape: dict, origin_xy, pixel_mm: float, resolution: tuple) -> dict:
    """Return a new shape dict in pixel coordinates from an mm-space shape."""
    width, height = resolution

    def to_px(point):
        col = (point[0] - origin_xy[0]) / pixel_mm
        row = (height - 1) - (point[1] - origin_xy[1]) / pixel_mm
        return (int(round(col)), int(round(row)))

    kind = shape["type"]
    if kind == "rect":
        c0 = to_px((shape["x"], shape["y"]))
        c1 = to_px((shape["x"] + shape["w"], shape["y"] + shape["h"]))
        x0, x1 = sorted((c0[0], c1[0]))
        y0, y1 = sorted((c0[1], c1[1]))
        return {"type": "rect", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    if kind == "circle":
        center = to_px((shape["cx"], shape["cy"]))
        return {
            "type": "circle",
            "cx": center[0],
            "cy": center[1],
            "r": int(round(shape["r"] / pixel_mm)),
        }
    # polygon
    return {"type": "polygon", "points": [list(to_px(point)) for point in shape["points"]]}
