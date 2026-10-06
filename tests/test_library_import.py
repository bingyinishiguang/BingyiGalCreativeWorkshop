"""手动图片导入的格式、尺寸、透明度和查重回归。"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from sprite_library import (
    LEVEL_OK,
    LEVEL_REJECT,
    LEVEL_WARN,
    SpriteLibrary,
    validate_import_candidate,
)


def _sprite(path: Path, size=(400, 600)) -> Path:
    """画一张真·透明立绘：全透明底 + 中间一个不透明主体。"""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((size[0] // 4, size[1] // 6, size[0] * 3 // 4, size[1] * 5 // 6),
                 fill=(240, 200, 220, 255))
    image.save(path)
    return path


def _opaque_png(path: Path, size=(400, 600)) -> Path:
    """带 alpha 通道但整张不透明 —— 典型的矩形背景图。"""
    Image.new("RGBA", size, (200, 180, 160, 255)).save(path)
    return path


#闸 1：格式白名单

@pytest.mark.parametrize("name", ["歌.mp3", "曲.wav", "文本.txt", "压缩.zip", "没有扩展名"])
def test_audio_and_non_image_extensions_are_rejected(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"x" * 5000)
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT
    assert "已拒绝" in result["reason"]


def test_audio_extension_gets_a_plain_language_reason(tmp_path):
    path = tmp_path / "某个歌曲.mp3"
    path.write_bytes(b"ID3\x03\x00\x00\x00" + b"\x00" * 5000)
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT
    assert "音频" in result["reason"], result["reason"]


#闸 2：真解码 / 真文件头

def test_audio_renamed_to_png_is_rejected_by_magic_bytes(tmp_path):
    path = tmp_path / "伪装.png"
    path.write_bytes(b"ID3\x03\x00\x00\x00" + b"\x00" * 5000)
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT
    assert "音频" in result["reason"], result["reason"]


def test_corrupt_image_is_rejected(tmp_path):
    path = tmp_path / "损坏.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"this is not a decodable image" * 100)
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT
    assert "已拒绝" in result["reason"]


def test_tiny_file_is_rejected(tmp_path):
    path = tmp_path / "空.png"
    path.write_bytes(b"")
    assert validate_import_candidate(path)["level"] == LEVEL_REJECT


def test_text_file_renamed_png_is_rejected(tmp_path):
    path = tmp_path / "说明.png"
    path.write_text("这其实是一段文字" * 200, encoding="utf-8")
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT


#闸 3/4：透明立绘判定 + 尺寸

def test_real_transparent_sprite_passes(tmp_path):
    result = validate_import_candidate(_sprite(tmp_path / "立绘.png"))
    assert result["level"] == LEVEL_OK, result["reason"]
    assert result["image"] is not None
    assert (result["width"], result["height"]) == (400, 600)


def test_jpeg_is_hard_rejected_as_rectangle_background(tmp_path):
    path = tmp_path / "背景.jpg"
    Image.new("RGB", (400, 600), (200, 180, 160)).save(path)
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT
    assert "矩形背景图" in result["reason"], result["reason"]


def test_opaque_png_is_rejected(tmp_path):
    result = validate_import_candidate(_opaque_png(tmp_path / "截图.png"))
    assert result["level"] == LEVEL_REJECT
    assert result["metrics"]["cornersOpaque"] is True


def test_too_small_image_is_rejected(tmp_path):
    path = tmp_path / "小.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(path)
    #补足文件大小，确保不是被「文件太小」拦下，而是被尺寸拦下
    result = validate_import_candidate(path)
    assert result["level"] == LEVEL_REJECT


def test_validation_does_not_write_anything(tmp_path):
    source = _sprite(tmp_path / "立绘.png")
    before = {p.name for p in tmp_path.iterdir()}
    validate_import_candidate(source)
    assert {p.name for p in tmp_path.iterdir()} == before


#入库 / 去重 / 强制导入

def test_import_transparent_sprite(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    result = lib.import_image(_sprite(tmp_path / "立绘.png"), "测试角色", tags=["测试"])
    assert result["status"] == "imported"
    assert result["character"] == "测试角色"
    item = lib.list(False)
    assert item["total"] == 1
    assert item["items"][0]["game"] == "本地导入"
    assert item["items"][0]["category"] == "normal"


def test_blank_character_falls_back_to_unnamed(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    result = lib.import_image(_sprite(tmp_path / "立绘.png"), "   ")
    assert result["character"] == "未命名"
    assert result["status"] == "imported"


def test_same_image_is_not_stored_twice(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    source = _sprite(tmp_path / "立绘.png")
    first = lib.import_image(source, "角色A")
    second = lib.import_image(source, "角色B")
    assert first["status"] == "imported"
    assert second["status"] == "duplicate"
    assert second["id"] == first["id"]
    assert lib.list(False)["total"] == 1


def test_opaque_png_needs_force_and_then_imports(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    source = _opaque_png(tmp_path / "截图.png")
    assert lib.import_image(source, "角色A")["status"] == "rejected"
    forced = lib.import_image(source, "角色A", force=True)
    assert forced["status"] == "imported", forced["reason"]
    assert lib.list(False)["total"] == 1


def test_audio_cannot_be_forced_in(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    path = tmp_path / "歌.mp3"
    path.write_bytes(b"ID3\x03\x00\x00\x00" + b"\x00" * 5000)
    result = lib.import_image(path, "角色A", force=True)
    assert result["status"] == "rejected"
    assert lib.list(False)["total"] == 0


def test_jpeg_cannot_be_forced_in(tmp_path):
    lib = SpriteLibrary(tmp_path / "lib")
    path = tmp_path / "背景.jpg"
    Image.new("RGB", (400, 600), (1, 2, 3)).save(path)
    assert lib.import_image(path, "角色A", force=True)["status"] == "rejected"
    assert lib.list(False)["total"] == 0


def _octagon(path: Path, corner: int = 30, hole: bool = True) -> Path:
    """八边形主体：四角透明，但四条边大部分被主体覆盖。"""
    image = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(corner, 0), (399 - corner, 0), (399, corner), (399, 599 - corner),
         (399 - corner, 599), (corner, 599), (0, 599 - corner), (0, corner)],
        fill=(230, 210, 225, 255),
    )
    if hole:
        draw.ellipse((120, 200, 279, 399), fill=(0, 0, 0, 0))
    image.save(path)
    return path


def test_warning_level_is_reachable(tmp_path):
    result = validate_import_candidate(_octagon(tmp_path / "贴边.png", hole=True))
    assert result["level"] == LEVEL_WARN, result["reason"]
    assert result["metrics"]["cornersOpaque"] is False
    assert 0.05 <= result["metrics"]["edgeTransparentRatio"] < 0.30
    assert result["metrics"]["overallTransparentRatio"] >= 0.02


def test_almost_fully_opaque_is_rejected_even_with_transparent_corners(tmp_path):
    result = validate_import_candidate(_octagon(tmp_path / "几乎不透明.png", hole=False))
    assert result["level"] == LEVEL_REJECT, result["reason"]
    assert result["metrics"]["overallTransparentRatio"] < 0.02


def test_import_keeps_tags_given_as_comma_string(tmp_path):
    library = SpriteLibrary(tmp_path / "Library")
    source = _sprite(tmp_path / "立绘.png")
    result = library.import_image(source, "用户填的角色", "本地导入, 常用", game="用户填的作品")
    assert result["status"] == "imported", result.get("reason")
    tags = result["item"].get("tags") or []
    assert "本地导入" in tags and "常用" in tags, f"字符串标签不能被丢掉：{tags}"
    #真的能按标签搜到
    assert library.list(False, tag="常用")["total"] == 1


def test_import_accepts_fullwidth_comma_in_tags(tmp_path):
    library = SpriteLibrary(tmp_path / "Library")
    result = library.import_image(_sprite(tmp_path / "立绘.png"), "角色", "标签甲，标签乙", game="作品")
    tags = result["item"].get("tags") or []
    assert "标签甲" in tags and "标签乙" in tags, f"全角逗号没拆开：{tags}"


def test_reimport_merges_new_tags_into_existing(tmp_path):
    library = SpriteLibrary(tmp_path / "Library")
    source = _sprite(tmp_path / "立绘.png")
    first = library.import_image(source, "角色", "原标签", game="作品")
    assert first["status"] == "imported"

    again = library.import_image(source, "角色", "补充标签", game="作品")
    assert again["status"] == "duplicate"
    tags = again["item"].get("tags") or []
    assert "补充标签" in tags, f"重复导入时新标签被忽略：{tags}"
    assert "原标签" in tags, f"重复导入不能丢掉原有标签：{tags}"
