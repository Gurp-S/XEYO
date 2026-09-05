from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
source = Image.open(ROOT / 'assets' / 'XEYO Context Pasture.png').convert('RGB')

def components(box, name):
    crop = source.crop(box)
    arr = np.asarray(crop, dtype=np.int16)
    bg = np.array([248, 243, 235], dtype=np.int16)
    delta = np.max(np.abs(arr - bg), axis=2)
    colorful = (delta > 26) & ((arr.max(axis=2) - arr.min(axis=2)) > 10)
    mask = Image.fromarray((colorful.astype(np.uint8) * 255), 'L').filter(ImageFilter.MaxFilter(5))
    m = np.asarray(mask) > 0
    h, w = m.shape
    seen = np.zeros_like(m)
    found = []
    for y in range(h):
        for x in range(w):
            if not m[y, x] or seen[y, x]:
                continue
            q = deque([(y, x)])
            seen[y, x] = 1
            xs, ys = [], []
            while q:
                cy, cx = q.popleft()
                xs.append(cx); ys.append(cy)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = 1
                            q.append((ny, nx))
            if len(xs) >= 12:
                found.append((len(xs), (box[0] + min(xs), box[1] + min(ys), box[0] + max(xs) + 1, box[1] + max(ys) + 1)))
    print(name)
    for area, bbox in sorted(found, key=lambda item: item[1][0]):
        print(area, bbox)

components((600, 42, 970, 112), 'grass row')
components((1030, 242, 1335, 300), 'butterfly row')
