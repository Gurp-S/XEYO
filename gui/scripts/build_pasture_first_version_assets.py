from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets' / 'XEYO Context Pasture.png'
OUT = ROOT / 'public' / 'pasture-first'


def remove_paper(image: Image.Image, tolerance: int = 28) -> Image.Image:
    rgba = image.convert('RGBA')
    rgb = np.asarray(rgba.convert('RGB'), dtype=np.int16)
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
    fringe = (~connected) & (distance <= tolerance + 10)
    alpha[fringe] = np.minimum(alpha[fringe], np.clip((distance[fringe] - tolerance) * 20, 0, 255).astype(np.uint8))
    rgba.putalpha(Image.fromarray(alpha, mode='L'))
    bbox = rgba.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def crop_asset(name: str, box: tuple[int, int, int, int], pad: int = 4) -> Image.Image:
    x0, y0, x1, y1 = box
    image = source.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    image = remove_paper(image)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    return image


source = Image.open(SOURCE).convert('RGB')
assets: list[tuple[str, tuple[int, int, int, int]]] = [
    # Pure grass clumps from the fourth and fifth entries of the source grass row.
    ('grass/grass-a.png', (802, 62, 846, 96)),
    ('grass/grass-b.png', (856, 61, 897, 96)),
    # Butterflies from the source natural-decoration row; no flower or insect substitutes.
    ('butterfly/butterfly-green.png', (1085, 259, 1107, 283)),
    ('butterfly/butterfly-yellow.png', (1123, 260, 1144, 279)),
    ('butterfly/butterfly-purple.png', (1160, 260, 1181, 279)),
    ('butterfly/butterfly-white.png', (1198, 260, 1218, 279)),
]

review: list[tuple[str, Image.Image]] = []
for name, box in assets:
    review.append((name, crop_asset(name, box)))

cell_w, cell_h = 220, 150
sheet = Image.new('RGBA', (cell_w * 3, cell_h * 2), (248, 244, 235, 255))
draw = ImageDraw.Draw(sheet)
for index, (name, image) in enumerate(review):
    x = (index % 3) * cell_w
    y = (index // 3) * cell_h
    thumb = image.copy()
    thumb.thumbnail((170, 100), Image.Resampling.NEAREST)
    sheet.alpha_composite(thumb, (x + (cell_w - thumb.width) // 2, y + 8))
    draw.text((x + 8, y + 120), name, fill=(38, 48, 42, 255))
sheet.save(OUT / 'review-contact-sheet.png', optimize=True)
print(f'Generated {len(review)} first-version assets under {OUT}')
