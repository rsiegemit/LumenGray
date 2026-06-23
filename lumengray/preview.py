"""Contact-sheet preview: a grid of sampled layer thumbnails for eyeballing."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def sample_indices(total: int, max_tiles: int) -> list[int]:
    """Pick up to max_tiles layer indices (0-based) spread evenly across the stack."""
    if total <= max_tiles:
        return list(range(total))
    step = total / max_tiles
    return [min(total - 1, int(i * step)) for i in range(max_tiles)]


def make_thumbnail(layer: np.ndarray, thumb_w: int) -> Image.Image:
    image = Image.fromarray(layer, mode="L")
    height = max(1, round(thumb_w * image.height / image.width))
    return image.resize((thumb_w, height), Image.NEAREST)


def build_contact_sheet(thumbs: list[tuple], cols: int, pad: int = 6) -> Image.Image:
    """Compose (layer_number, thumbnail) tiles into a labeled grid on dark gray."""
    if not thumbs:
        raise ValueError("no thumbnails to compose")
    tile_w = thumbs[0][1].width
    tile_h = thumbs[0][1].height
    label_h = 14
    rows = (len(thumbs) + cols - 1) // cols
    sheet_w = cols * tile_w + (cols + 1) * pad
    sheet_h = rows * (tile_h + label_h) + (rows + 1) * pad
    sheet = Image.new("L", (sheet_w, sheet_h), 40)
    draw = ImageDraw.Draw(sheet)
    for position, (number, thumb) in enumerate(thumbs):
        col, row = position % cols, position // cols
        x = pad + col * (tile_w + pad)
        y = pad + row * (tile_h + label_h + pad)
        draw.text((x, y), f"#{number}", fill=200)
        sheet.paste(thumb, (x, y + label_h))
    return sheet
