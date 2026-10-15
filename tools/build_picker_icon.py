"""Build the neutral gallery icon used by the companion executable and Qt."""
from pathlib import Path

from PIL import Image, ImageDraw


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    image = Image.new('RGBA', (256, 256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), radius=52, fill='#18547c')
    for x in (54, 139):
        for y in (54, 139):
            draw.rounded_rectangle((x, y, x + 63, y + 63), radius=10,
                                   outline='#c5ecff', width=9)
    ui = root / 'ui'
    ui.mkdir(parents=True, exist_ok=True)
    image.save(ui / 'picker-icon.png')
    image.save(ui / 'picker-icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])


if __name__ == '__main__':
    build()
