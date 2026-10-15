"""Build every application icon from the checked-in workshop logo."""
import sys
from pathlib import Path

from PIL import Image


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    ui = root / 'ui'
    original = ui / 'assets' / 'brand-source' / 'logo.png'
    with Image.open(original if original.is_file() else ui / 'favicon.png') as source:
        image = source.convert('RGBA')
    if original.is_file():
        sys.path.insert(0, str(root))
        from tools.build_brand_assets import _chroma_key
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        image = _chroma_key(image)
        box = image.getbbox()
        if box:
            image = image.crop(box)
    side = max(image.size)
    square = Image.new('RGBA', (side, side))
    square.alpha_composite(image, ((side-image.width)//2, (side-image.height)//2))
    image = square.resize((256, 256), Image.Resampling.LANCZOS)
    image.save(ui / 'picker-icon.png')
    image.resize((64, 64), Image.Resampling.LANCZOS).save(ui / 'favicon.png')
    sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
    image.save(ui / 'app.ico', sizes=sizes)
    (ui / 'picker-icon.ico').write_bytes((ui / 'app.ico').read_bytes())
    assets = root / 'brand-assets'
    assets.mkdir(exist_ok=True)
    (assets / 'app.ico').write_bytes((ui / 'app.ico').read_bytes())
    image.resize((55, 55), Image.Resampling.LANCZOS).convert('RGB').save(assets / 'inno-wizard-small.bmp')
    wizard = Image.new('RGB', (164, 314), '#f0f7ff')
    logo = image.resize((144, 144), Image.Resampling.LANCZOS)
    wizard.paste(logo, (10, 70), logo)
    wizard.save(assets / 'inno-wizard.bmp')


if __name__ == '__main__':
    build()
