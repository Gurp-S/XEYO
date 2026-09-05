from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
source = Image.open(ROOT / 'assets' / 'XEYO Context Pasture.png').convert('RGB')
regions = {
    'grass-panel': (570, 25, 1000, 115),
    'nature-panel': (990, 180, 1528, 315),
    'butterfly-row': (1030, 242, 1335, 300),
}
thumbs = []
for name, box in regions.items():
    crop = source.crop(box)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST)
    thumbs.append((name, crop))
canvas = Image.new('RGB', (max(image.width for _, image in thumbs), sum(image.height + 42 for _, image in thumbs)), (248, 244, 235))
draw = ImageDraw.Draw(canvas)
y = 0
for name, image in thumbs:
    draw.text((8, y + 5), f'{name} source crop', fill=(40, 40, 40))
    y += 30
    canvas.paste(image, (0, y))
    y += image.height + 12
out = ROOT / 'public' / 'pasture-v2' / 'first-version-source-inspection.png'
out.parent.mkdir(parents=True, exist_ok=True)
canvas.save(out, optimize=True)
print(out)
print('regions:', regions)
