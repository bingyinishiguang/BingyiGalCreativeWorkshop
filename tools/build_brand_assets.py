#!/usr/bin/env python3
"""从品牌素材目录生成头像、签名、图标与安装向导资源。"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

#路径
ROOT = pathlib_root = Path(__file__).resolve().parent.parent


def _default_brand_dir() -> Path:
    """优先使用 BINGYI_BRAND_DIR；未配置时使用项目内的私有素材目录。"""
    env = os.environ.get("BINGYI_BRAND_DIR")
    if env:
        return Path(env)
    return ROOT / "private-assets" / "brand"


BRAND_DIR = _default_brand_dir()
UI = ROOT / "ui"
OUT = ROOT / "brand-assets"

AVATAR_SRC = BRAND_DIR / "BingyiAvatar_冰翼形象" / "我的女生头像.png"
LOGO_SRC = BRAND_DIR / "Logo_标识" / "冰翼标.png"

SIGN_TEXT = "冰翼逆时光"


def _font(size: int):
    """优先用有笔触的衬线 CJK；找不到回退默认。"""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    from PIL import ImageFont
    return ImageFont.load_default()


def build_avatar() -> None:
    if not AVATAR_SRC.exists():
        print(f"[skip] 头像源缺失：{AVATAR_SRC}")
        return
    img = Image.open(AVATAR_SRC).convert("RGBA")
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2))
    img = img.resize((192, 192), Image.LANCZOS)
    #圆形裁切
    mask = Image.new("L", (192, 192), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 192, 192), fill=255)
    out = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    out.save(UI / "avatar.png")
    print("[ok] ui/avatar.png")


def build_signature() -> None:
    """环形弧形文字：把每个字沿圆周排布，烘焙成 SVG path（用 fontTools 取轮廓）。"""
    try:
        from fontTools.ttLib import TTFont
        from fontTools.pens.svgPathPen import SVGPathPen
    except Exception as e:
        print(f"[skip] fontTools 不可用：{e}")
        return

    font_path = None
    for c in ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]:
        if Path(c).exists():
            font_path = c
            break
    if not font_path:
        print("[skip] 未找到 CJK 字体")
        return

    font = TTFont(font_path, fontNumber=0)
    cmap = font.getBestCmap()
    glyphset = font.getGlyphSet()
    upm = font["head"].unitsPerEm

    #尺寸：viewBox 200x200，头像半径约 62，文字基线半径 82（贴环，76px 顶栏内不溢出）
    size = 200
    cx = cy = size / 2
    text_r = 82
    scale = 26 / upm  #字高约 26px

    n = len(SIGN_TEXT)
    #沿头像下方弧线从左到右排布（底部弧线，字头朝圆心）
    step = 26  #每字角距
    start_angle = 90 + (n - 1) * step / 2

    paths = []
    for i, ch in enumerate(SIGN_TEXT):
        code = ord(ch)
        if code not in cmap:
            continue
        glyph_name = cmap[code]
        glyph = glyphset[glyph_name]
        pen = SVGPathPen(glyphset)
        glyph.draw(pen)
        d = pen.getCommands()
        if not d.strip():
            continue
        angle = start_angle - i * step
        rad = math.radians(angle)
        #字形中心放在圆周上，并让字形随角度旋转（字头朝圆心，位于头像下方）
        gx = cx + text_r * math.cos(rad)
        gy = cy + text_r * math.sin(rad)
        rot = angle - 90  #底部朝外
        #先缩放、绕字形中心旋转、再平移到圆周点
        t = (f"translate({gx:.2f} {gy:.2f}) rotate({rot:.1f}) "
             f"scale({scale:.4f} {-scale:.4f}) translate({-upm/2:.1f} {-upm/2:.1f})")
        paths.append(f'<path transform="{t}" d="{d}"/>')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">\n'
        f'  <g fill="none" stroke="none">\n'
        f'    <circle cx="{cx}" cy="{cy}" r="{text_r}" fill="none"/>\n'
        f'  </g>\n'
        f'  <g fill="url(#grad)" stroke="#eaf5ff" stroke-width="0.6">\n'
        f'    <defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#2770ba"/><stop offset="1" stop-color="#5a9bd8"/>'
        f'</linearGradient></defs>\n'
        + "\n".join(paths) +
        f'\n  </g>\n</svg>\n'
    )
    (UI / "signature.svg").write_text(svg, encoding="utf-8")
    print("[ok] ui/signature.svg")


def _chroma_key(img: Image.Image) -> Image.Image:
    """去绿幕：绿色域透明 + 去溢色 + 边缘羽化。"""
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            #绿色强度
            if g > 90 and g > r * 1.15 and g > b * 1.15:
                #完全绿 → 透明
                alpha = 0
                #去溢色：压低绿
                g = min(g, max(r, b))
                px[x, y] = (r, g, b, alpha)
            elif g > r and g > b:
                #边缘过渡 → 部分透明 + 去绿
                alpha = int(255 * (1 - (g - max(r, b)) / 80))
                alpha = max(0, min(255, alpha))
                g = min(g, max(r, b) + 8)
                px[x, y] = (r, g, b, min(a, alpha))
    return img


def build_logo_assets() -> None:
    if not LOGO_SRC.exists():
        print(f"[skip] 绿幕 logo 源缺失：{LOGO_SRC}")
        return
    OUT.mkdir(exist_ok=True)
    base = Image.open(LOGO_SRC).convert("RGBA")
    #产物最大 512px，先缩再逐像素抠图，避免大图循环过慢
    base.thumbnail((512, 512), Image.LANCZOS)
    keyed = _chroma_key(base)
    #裁剪到内容包围盒
    bbox = keyed.getbbox()
    if bbox:
        keyed = keyed.crop(bbox)
    keyed.save(OUT / "logo-transparent.png")

    #favicon（多尺寸 PNG，浏览器取合适尺寸）
    fav = keyed.copy()
    fav.thumbnail((64, 64), Image.LANCZOS)
    fav.save(UI / "favicon.png")
    print("[ok] ui/favicon.png")

    #.ico（多尺寸）
    ico = keyed.copy()
    ico.save(OUT / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("[ok] brand-assets/app.ico")

    #Inno 向导图（164x314 左侧大图 + 55x58 小图）
    wiz = Image.new("RGBA", (164, 314), (250, 252, 255, 255))
    logo = keyed.copy()
    logo.thumbnail((150, 220), Image.LANCZOS)
    wiz.paste(logo, ((164 - logo.width) // 2, (314 - logo.height) // 2), logo)
    wiz.convert("RGB").save(OUT / "inno-wizard.bmp")
    small = Image.new("RGBA", (55, 58), (250, 252, 255, 255))
    lg = keyed.copy()
    lg.thumbnail((50, 50), Image.LANCZOS)
    small.paste(lg, ((55 - lg.width) // 2, (58 - lg.height) // 2), lg)
    small.convert("RGB").save(OUT / "inno-wizard-small.bmp")
    print("[ok] brand-assets/inno-wizard*.bmp")


def main() -> int:
    UI.mkdir(exist_ok=True)
    build_avatar()
    build_signature()
    build_logo_assets()
    print("[done] 品牌资产处理完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
