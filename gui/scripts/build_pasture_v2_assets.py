from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "XEYO Context Pasture.png"
OUT = ROOT / "public" / "pasture-v2"


def remove_connected_paper(image: Image.Image, tolerance: int = 26) -> Image.Image:
    """Remove only the edge-connected paper background; preserve pale sprites."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    bg = rgb[0, 0]
    distance = np.max(np.abs(rgb - bg), axis=2)
    candidate = distance <= tolerance
    h, w = candidate.shape
    connected = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(w):
        if candidate[0, x]: queue.append((0, x))
        if candidate[h - 1, x]: queue.append((h - 1, x))
    for y in range(h):
        if candidate[y, 0]: queue.append((y, 0))
        if candidate[y, w - 1]: queue.append((y, w - 1))
    while queue:
        y, x = queue.popleft()
        if connected[y, x]:
            continue
        connected[y, x] = True
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and candidate[ny, nx] and not connected[ny, nx]:
                queue.append((ny, nx))
    alpha = np.full((h, w), 255, dtype=np.uint8)
    alpha[connected] = 0
    # Soften only the outer fringe of paper-colored antialiasing.
    near = np.clip(255 - (distance * 16), 0, 255).astype(np.uint8)
    alpha[connected] = 0
    fringe = (~connected) & (distance <= tolerance + 12)
    alpha[fringe] = np.minimum(alpha[fringe], near[fringe])
    out = image.convert("RGBA")
    out.putalpha(Image.fromarray(alpha, mode="L"))
    bbox = out.getbbox()
    return out.crop(bbox) if bbox else out


def crop(name: str, box: tuple[int, int, int, int], *, alpha: bool = True, tolerance: int = 26) -> Image.Image:
    image = source.crop(box)
    if alpha:
        image = remove_connected_paper(image, tolerance=tolerance)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    return image


def crop_many(items: Iterable[tuple[str, tuple[int, int, int, int]]], *, alpha: bool = True) -> list[tuple[str, Image.Image]]:
    return [(name, crop(name, box, alpha=alpha)) for name, box in items]


source = Image.open(SOURCE).convert("RGB")

# Coordinates are deliberately grouped by the labelled regions in the source sheet.
# Background strips: the six long rows in the lower-right background panel.
backgrounds = [
    ("backgrounds/day.png", (1000, 592, 1525, 630)),
    ("backgrounds/cloudy.png", (1000, 631, 1525, 669)),
    ("backgrounds/sunset.png", (1000, 670, 1525, 708)),
    ("backgrounds/dusk.png", (1000, 709, 1525, 747)),
    ("backgrounds/night.png", (1000, 748, 1525, 786)),
    ("backgrounds/fog.png", (1000, 787, 1525, 825)),
]
for name, box in backgrounds:
    crop(name, box, alpha=False)

# Ground tiles: six independent low horizontal tiles in the lower-right panel.
grounds = [
    ("grounds/meadow.png", (989, 875, 1072, 928)),
    ("grounds/flower-meadow.png", (1081, 875, 1157, 928)),
    ("grounds/grass-edge.png", (1158, 875, 1242, 928)),
    ("grounds/stone-edge.png", (1243, 875, 1327, 928)),
    ("grounds/rock-edge.png", (1338, 875, 1412, 928)),
    ("grounds/lush-edge.png", (1413, 875, 1525, 928)),
]
for name, box in grounds:
    crop(name, box, alpha=True, tolerance=30)

# Representative actors; each crop is a single pose from the animal panel.
actors = [
    ("actors/rabbit-eat.png", (66, 48, 112, 108)),
    ("actors/rabbit-rest.png", (482, 48, 548, 108)),
    ("actors/fox-rest.png", (62, 112, 112, 178)),
    ("actors/sheep-graze.png", (66, 178, 116, 242)),
    ("actors/deer-stand.png", (66, 244, 126, 320)),
    ("actors/bird-fly.png", (58, 420, 104, 486)),
    ("actors/butterfly.png", (1210, 272, 1270, 324)),
]
for name, box in actors:
    crop(name, box, tolerance=24)

# Representative plants from the labelled plant panel.
plants = [
    ("plants/grass.png", (632, 48, 686, 110)),
    ("plants/flower.png", (632, 112, 690, 178)),
    ("plants/bush.png", (632, 178, 700, 246)),
    ("plants/sapling.png", (632, 244, 694, 318)),
    ("plants/tree.png", (630, 316, 700, 402)),
    ("plants/mushroom.png", (632, 436, 686, 494)),
    ("plants/stone.png", (1000, 204, 1054, 246)),
]
for name, box in plants:
    crop(name, box, tolerance=24)

# Small atmosphere pieces; kept independent so CSS can control opacity and parallax.
atmosphere = [
    ("atmosphere/cloud.png", (1060, 42, 1132, 83)),
    ("atmosphere/sun.png", (1214, 39, 1265, 86)),
    ("atmosphere/moon.png", (1358, 40, 1408, 87)),
    ("atmosphere/sparkle.png", (1430, 40, 1490, 90)),
    ("atmosphere/rain.png", (1080, 112, 1148, 172)),
]
for name, box in atmosphere:
    crop(name, box, tolerance=24)

# Contact sheet for local visual review, not used by the app.
review_items: list[tuple[str, Image.Image]] = []
for group in ("backgrounds", "grounds", "actors", "plants", "atmosphere"):
    for path in sorted((OUT / group).glob("*.png")):
        review_items.append((f"{group}/{path.name}", Image.open(path).convert("RGBA")))
cell_w, cell_h = 150, 118
sheet = Image.new("RGBA", (cell_w * 4, cell_h * ((len(review_items) + 3) // 4)), (245, 239, 228, 255))
draw = ImageDraw.Draw(sheet)
for index, (name, image) in enumerate(review_items):
    x = (index % 4) * cell_w
    y = (index // 4) * cell_h
    thumb = image.copy()
    thumb.thumbnail((120, 82), Image.Resampling.NEAREST)
    sheet.alpha_composite(thumb, (x + (cell_w - thumb.width) // 2, y + 4))
    draw.text((x + 6, y + 92), name, fill=(52, 60, 54, 255))
sheet.save(OUT / "review-contact-sheet.png", optimize=True)

print(f"Generated {len(list(OUT.rglob('*.png')))} PNG assets under {OUT}")
