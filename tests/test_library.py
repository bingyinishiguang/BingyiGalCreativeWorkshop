import os
import tempfile
import unittest
import sqlite3
from pathlib import Path

from PIL import Image

from sprite_composer import discover_pack_game_roots, exports_root, game_directories, scan_characters, scan_lime_poses, web_catalog, web_composite
from sprite_library import SpriteLibrary
from txt_parser import scan_txt_library


class LibraryRecoveryTest(unittest.TestCase):
    """库文件损坏 / 老库有重复行时必须还能起来。"""

    def test_corrupt_database_is_quarantined_and_rebuilt(self):
        import app_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Library"
            root.mkdir(parents=True)
            (root / app_paths.LIBRARY_DB_NAME).write_bytes(b"definitely not a sqlite database" * 8)
            library = SpriteLibrary(root)
            item = library.save("G", "C", "B", "f1", "normal",
                                Image.new("RGBA", (40, 80), (1, 2, 3, 255)), ["t"])
            self.assertTrue(item["id"])
            quarantined = list(root.glob("*.broken-*"))
            self.assertTrue(quarantined, "坏库必须改名留证，绝不能直接删掉用户数据")

    def test_history_hash_conflict_does_not_wipe_or_quarantine(self):
        import shutil

        import app_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Library"
            library = SpriteLibrary(root)
            saved = library.save("G", "C", "B", "f1", "normal",
                                 Image.new("RGBA", (60, 120), (10, 200, 30, 255)), ["重要标签"])
            source = library.file(saved["id"], False)

            connection = sqlite3.connect(root / app_paths.LIBRARY_DB_NAME)
            connection.row_factory = sqlite3.Row
            connection.execute("DROP INDEX IF EXISTS sprites_unique_live")
            digest = connection.execute("SELECT content_hash FROM sprites WHERE id = ?",
                                        (saved["id"],)).fetchone()[0]
            connection.execute("UPDATE sprites SET content_hash = '' WHERE id = ?", (saved["id"],))

            second_relative = "images/zz/cccccccccccccccccccccccccccccccc.png"
            destination = root / second_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            connection.execute(
                "INSERT INTO sprites (id, game, character, body, face, category, relative_path,"
                " width, height, saved_at, content_hash, updated_at, deleted_at)"
                " VALUES ('cccccccccccccccccccccccccccccccc', 'G', 'C', 'B', 'f1', 'normal', ?, 60, 120,"
                " '2026-01-01', ?, '2026-01-01', '')",
                (second_relative, digest))
            connection.commit()
            connection.close()

            reopened = SpriteLibrary(root)
            self.assertEqual(reopened.list(False, limit=10)["total"], 2, "两条记录都必须保留")
            self.assertFalse(list(root.glob("*.broken-*")), "有冲突不等于库坏了，不能隔离整个库")
            tags = [item.get("tags") or [] for item in reopened.list(False, limit=10)["items"]]
            self.assertIn(["重要标签"], tags, "用户标签不能丢")


class SpriteLibraryTest(unittest.TestCase):
    def test_index_search_and_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            image = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
            image.putpixel((16, 20), (10, 20, 30, 255))
            normal = library.save("作品甲", "角色甲", "校服", "a0001", "normal", image)
            special = library.save("作品甲", "角色乙", "泳衣", "a0002", "swimwear", image)
            restarted = SpriteLibrary(Path(directory) / "Library")
            self.assertEqual(restarted.list(False)["total"], 1)
            self.assertEqual(restarted.list(True)["total"], 1)
            self.assertEqual(restarted.list(False, search="角色甲")["items"][0]["id"], normal["id"])
            self.assertEqual(restarted.list(False, search="角色乙")["total"], 0)
            self.assertEqual(restarted.list(False, game="不存在")["total"], 0)
            self.assertIsNone(restarted.file(special["id"], False))
            self.assertIsNotNone(restarted.file(special["id"], True))
            self.assertIsNone(restarted.file(normal["id"], True))

    def test_metadata_filters_duplicate_missing_and_trash(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            image = Image.new("RGBA", (16, 20), (0, 0, 0, 0))
            image.putpixel((8, 10), (20, 30, 40, 255))
            saved = library.save("作品", "角色", "校服", "a0001", "normal", image)
            duplicate = library.save("作品", "角色", "校服", "a0001", "normal", image.copy())
            self.assertEqual(duplicate["id"], saved["id"])
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(library.list(False)["total"], 1)

            updated = library.update(saved["id"], False, "开场微笑", "第一集使用", True, ["开心", "开场", "开心"])
            self.assertCountEqual(updated["tags"], ["开心", "开场"])
            self.assertTrue(updated["favorite"])
            self.assertEqual(library.list(False, search="第一集")["total"], 1)
            self.assertEqual(library.list(False, tag="开心")["total"], 1)
            self.assertEqual(library.list(False, favorite=True)["total"], 1)
            self.assertIsNone(library.update(saved["id"], True, "越区", "", False, []))

            path = library.file(saved["id"], False)
            path.unlink()
            self.assertTrue(library.list(False)["items"][0]["missing"])
            repaired = library.save("作品", "角色", "校服", "a0001", "normal", image)
            self.assertTrue(repaired["repaired"])
            self.assertTrue(path.is_file())

            moved = library.move_to_trash(saved["id"], False)
            self.assertTrue(moved["deletedAt"])
            self.assertEqual(library.list(False)["total"], 0)
            self.assertEqual(library.list(False, trash=True)["total"], 1)
            self.assertIsNone(library.restore(saved["id"], True))
            self.assertIsNotNone(library.restore(saved["id"], False))
            library.move_to_trash(saved["id"], False)
            self.assertTrue(library.delete_permanently(saved["id"], False))
            self.assertEqual(library.list(False, trash=True)["total"], 0)

    def test_legacy_database_migrates_without_losing_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Library"
            image_dir = root / "images" / "aa"
            image_dir.mkdir(parents=True)
            item_id = "a" * 32
            Image.new("RGBA", (8, 12), (1, 2, 3, 255)).save(image_dir / f"{item_id}.png")
            connection = sqlite3.connect(root / "library.sqlite3")
            connection.execute("""CREATE TABLE sprites (
                id TEXT PRIMARY KEY, game TEXT NOT NULL, character TEXT NOT NULL,
                body TEXT NOT NULL, face TEXT NOT NULL, category TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE, width INTEGER NOT NULL,
                height INTEGER NOT NULL, saved_at TEXT NOT NULL)""")
            connection.execute("INSERT INTO sprites VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (item_id, "旧作品", "旧角色", "旧姿势", "a0001", "normal",
                                f"images/aa/{item_id}.png", 8, 12, "2026-09-28T12:00:00+08:00"))
            connection.commit()
            connection.close()

            library = SpriteLibrary(root)
            result = library.list(False)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["character"], "旧角色")
            self.assertFalse(result["items"][0]["missing"])
            self.assertTrue(library.file(item_id, False).is_file())

    def test_legacy_chinese_layout_migrates_to_ascii(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Library"
            legacy_images = root / "图片" / "aa"
            legacy_images.mkdir(parents=True)
            item_id = "b" * 32
            Image.new("RGBA", (8, 12), (1, 2, 3, 255)).save(legacy_images / f"{item_id}.png")
            connection = sqlite3.connect(root / "立绘库.sqlite3")
            connection.execute("""CREATE TABLE sprites (
                id TEXT PRIMARY KEY, game TEXT NOT NULL, character TEXT NOT NULL,
                body TEXT NOT NULL, face TEXT NOT NULL, category TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE, width INTEGER NOT NULL,
                height INTEGER NOT NULL, saved_at TEXT NOT NULL)""")
            connection.execute("INSERT INTO sprites VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (item_id, "旧作品", "旧角色", "旧姿势", "a0001", "normal",
                                f"图片/aa/{item_id}.png", 8, 12, "2026-09-28T12:00:00+08:00"))
            connection.commit()
            connection.close()

            library = SpriteLibrary(root)
            result = library.list(False)
            self.assertEqual(result["total"], 1)
            self.assertFalse(result["items"][0]["missing"], "旧库迁移后不该报文件丢失")
            self.assertTrue(library.file(item_id, False).is_file())
            self.assertTrue((root / "images" / "aa" / f"{item_id}.png").is_file())
            self.assertTrue((root / "library.sqlite3").is_file())

    def test_png_accessory_codes_are_not_faces(self):
        root = Path(__file__).resolve().parents[1]
        games = game_directories(discover_pack_game_roots(root))
        if "常轨脱离" not in games:
            self.skipTest("未提供 PNG 坐标素材")
        characters = scan_characters(games["常轨脱离"])
        self.assertTrue(characters)
        faces = [layer.name for character in characters.values() for layer in character.faces]
        self.assertTrue(faces)
        self.assertFalse(any(name[1:5] in {"0097", "0098", "0099"} for name in faces))

    def test_real_three_adapters_and_alpha_padding(self):
        root = Path(__file__).resolve().parents[1]
        roots = discover_pack_game_roots(root)
        games = game_directories(roots)
        if not {"常轨脱离", "LimeLightLemonadeJam"} <= games.keys():
            self.skipTest("未提供三种适配器的本地素材")
        characters = scan_characters(games["常轨脱离"])
        lime = scan_lime_poses(games["LimeLightLemonadeJam"])
        txt = {}
        for pack_root in roots:
            found, warnings = scan_txt_library(pack_root)
            self.assertFalse(warnings, warnings[:3])
            txt.update(found)
        catalog = web_catalog(characters, lime, txt)
        txt_game = next((name for name in txt if name not in ("常轨脱离", "LimeLightLemonadeJam")), None)
        if txt_game is None:
            self.skipTest("未提供 TXT 适配器的本地素材")
        output_root = exports_root(root)
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            for game in ("常轨脱离", "LimeLightLemonadeJam", txt_game):
                choice = None
                for character, data in catalog[game]["characters"].items():
                    for body, faces in data["bodies"].items():
                        if data["bodyCategories"][body] == "normal" and faces:
                            choice = (character, body, faces[0])
                            break
                    if choice:
                        break
                self.assertIsNotNone(choice, game)
                character, body, face = choice
                image = web_composite(game, character, body, face, characters, lime, txt)
                item = library.save(game, character, body, face, "normal", image)
                with Image.open(library.file(item["id"], False)) as saved:
                    self.assertEqual(saved.mode, "RGBA")
                    box = saved.getbbox()
                    self.assertIsNotNone(box)
                    self.assertGreaterEqual(box[0], 4)
                    self.assertGreaterEqual(box[1], 4)
                    self.assertGreaterEqual(saved.width - box[2], 4)
                    self.assertGreaterEqual(saved.height - box[3], 4)
            self.assertEqual(SpriteLibrary(Path(directory) / "Library").list(False)["total"], 3)


if __name__ == "__main__":
    unittest.main()

def test_trash_keeps_thumbnail_but_delete_drops_it(tmp_path):
    from PIL import Image

    from sprite_library import SpriteLibrary

    library = SpriteLibrary(tmp_path / "Library")
    image = Image.new("RGBA", (60, 120), (10, 200, 30, 255))
    first = library.save("G", "C", "B", "f1", "normal", image, ["t"])
    second = library.save("G", "C", "B", "f2", "normal", image, ["t"])
    thumbs = lambda: sorted(path.name for path in (tmp_path / "Library" / "thumbs").glob("*.webp"))
    assert len(thumbs()) == 2

    library.move_to_trash(first["id"], False)
    assert len(thumbs()) == 2, "进回收站必须保留缩略图（列表还要用它）"

    library.delete_permanently(first["id"], False)
    assert len(thumbs()) == 1, "永久删除应清掉该条的缩略图缓存"

    library.move_to_trash(second["id"], False)
    library.delete_permanently(second["id"], False)
    assert thumbs() == [], f"全部删除后不应有残留缩略图：{thumbs()}"


def test_orphan_scan_and_cleanup_are_safe(tmp_path):
    import os
    import time

    from PIL import Image, ImageDraw

    library = SpriteLibrary(tmp_path / "Library")
    image = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((140, 150, 260, 600), fill=(200, 30, 30, 255))
    source = tmp_path / "正常.png"
    image.save(source)
    library.import_image(source, "角色", "标签", game="作品")


    orphan_dir = library.images / "zz"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / ("a" * 32 + ".png")
    image.save(orphan)
    orphan_thumb = library.thumbs / ("b" * 32 + ".webp")
    orphan_thumb.write_bytes(b"fake")
    old = time.time() - 7200
    os.utime(orphan, (old, old))
    os.utime(orphan_thumb, (old, old))

    found = library._collect_orphans()
    assert orphan in found["images"]
    assert orphan_thumb in found["thumbs"]


    fresh = orphan_dir / ("c" * 32 + ".png")
    image.save(fresh)
    assert fresh not in library._collect_orphans()["images"]


    outside = tmp_path / "不该被删.png"
    image.save(outside)
    removed = library.delete_orphans([*found["images"], *found["thumbs"], outside])
    assert removed == 2, f"只应删 2 个，实际 {removed}"
    assert outside.is_file(), "库目录之外的文件绝不能被删"
    assert fresh.is_file(), "新文件不能被删"
    assert library.list(False, limit=10)["total"] == 1, "正常记录不受影响"


def test_head_crop_magnifies_the_face(tmp_path):
    import io as _io

    from PIL import Image, ImageDraw

    from sprite_library import SpriteLibrary

    library = SpriteLibrary(tmp_path / "Library")

    width, height = 360, 1154
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 40, 240, 200), fill=(240, 210, 170, 255))
    draw.rectangle((130, 220, 230, 900), fill=(80, 120, 200, 255))
    source = tmp_path / "立绘.png"
    image.save(source)
    saved = library.import_image(source, "角色", "标签", game="作品")
    assert saved["status"] == "imported", saved.get("reason")
    item_id = saved["id"]

    data = library.head_bytes(item_id)
    assert data, "头部特写必须能生成"
    with Image.open(_io.BytesIO(data)) as head:
        head_w, head_h = head.size

    assert head_h < height, "头部特写不该是整图"

    full_thumb_w = round(width * min(1.0, 256 / height))
    assert head_w > full_thumb_w * 1.5, (
        f"头部特写应比整图缩略更宽（{head_w} vs {full_thumb_w}）——这才是放大的意义")


    path = library.head_path(item_id)
    assert path is not None and path.is_file(), "head_path 必须落盘一个缓存文件"
    assert path.stat().st_size > 0
    assert library.head_path(item_id) == path, "第二次应直接命中缓存"


    assert library.head_bytes("f" * 32) is None
    assert library.head_path("not-a-valid-id") is None


def test_head_cache_is_dropped_on_delete_and_not_returned_for_unknown_id(tmp_path):

    from PIL import Image, ImageDraw

    from sprite_library import SpriteLibrary

    library = SpriteLibrary(tmp_path / "Library")

    image = Image.new("RGBA", (360, 1154), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 20, 300, 1100), fill=(200, 100, 100, 255))
    source = tmp_path / "立绘.png"
    image.save(source)
    saved = library.import_image(source, "角色", "标签", game="作品")
    assert saved["status"] == "imported", saved.get("reason")
    item_id = saved["id"]


    head = library.head_path(item_id)
    assert head is not None and head.is_file()
    assert head.name == f"{item_id}.head.png"


    ghost = "0" * 32
    (library.thumbs / f"{ghost}.head.png").write_bytes(head.read_bytes())
    assert library.head_bytes(ghost) is None, "前提：DB 里没有这个 id"
    assert library.head_path(ghost) is None, (
        "命中缓存前必须校验来源：DB 里没有的条目，不能凭磁盘上的同名文件就返回")


    thumb = library.thumbnail_path(item_id)
    assert thumb.is_file(), "前提：缩略图已生成"

    trashed = library.move_to_trash(item_id, False)
    assert trashed, "移到回收站应成功"
    assert library.head_bytes(item_id) is None, "已进回收站的条目不该还能生成头图"
    assert library.head_path(item_id) is None, (
        "已进回收站的条目不该还能拿到头部特写 —— "
        "命中缓存前必须校验来源，否则会显示已删除条目的人脸图")


    assert library.delete_permanently(item_id, False), "清空回收站应成功"
    assert library.head_path(item_id) is None
    assert not head.exists(), f"永久删除后 .head.png 仍在：{head}"
    assert not thumb.exists(), f"永久删除后 .webp 仍在：{thumb}"


def test_orphan_scan_ignores_head_cache(tmp_path):
    import time as _time

    from PIL import Image, ImageDraw

    from sprite_library import SpriteLibrary

    library = SpriteLibrary(tmp_path / "Library")

    image = Image.new("RGBA", (360, 1154), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 20, 300, 1100), fill=(100, 200, 100, 255))
    source = tmp_path / "立绘.png"
    image.save(source)
    saved = library.import_image(source, "角色", "标签", game="作品")
    assert saved["status"] == "imported", saved.get("reason")
    item_id = saved["id"]

    head = library.head_path(item_id)
    assert head is not None and head.is_file()


    old = _time.time() - 4000
    os.utime(head, (old, old))

    orphans = library._collect_orphans(minimum_age_seconds=900)
    reported = [p.name for p in orphans["thumbs"]]
    assert f"{item_id}.head.png" not in reported, (
        f"正常的头部特写缓存被误报成孤儿：{reported}")


def test_wal_checkpoint_makes_copied_database_readable(tmp_path):
    import shutil
    import sqlite3

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    database = source / "library.sqlite3"

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sprites (id TEXT PRIMARY KEY, name TEXT)")
    for index in range(100):
        connection.execute("INSERT INTO sprites VALUES (?, ?)", (f"id{index}", f"name{index}"))
    connection.commit()


    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(database, target / "library.sqlite3")

    with sqlite3.connect(target / "library.sqlite3") as probe:
        count = probe.execute("SELECT COUNT(*) FROM sprites").fetchone()[0]
    assert count == 100, f"checkpoint 后复制出来的库必须完整，实际 {count} 行"
    connection.close()
