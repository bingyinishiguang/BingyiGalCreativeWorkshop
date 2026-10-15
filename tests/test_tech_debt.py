"""素材包原子复制、图库并发写入与 PBD 读取上限回归。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import pack_import
import pbd_parser
from sprite_library import SpriteLibrary


def _sprite(seed: int = 0) -> Image.Image:
    image = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    image.putpixel((20, 40), ((seed * 11) % 255, 40, 50, 255))
    return image


class CopyPackAtomicTest(unittest.TestCase):
    """复制失败不能留下半截目录。"""

    def test_failed_copy_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "某作品"
            (source / "games").mkdir(parents=True)
            (source / "games" / "a.txt").write_text("x", encoding="utf-8")
            packs = root / "packs"
            packs.mkdir()


            with patch("pack_import.shutil.copytree", side_effect=OSError("磁盘已满")):
                with self.assertRaises(OSError):
                    pack_import.copy_pack(source, packs)

            self.assertFalse((packs / "某作品").exists(), "失败后不该有半截目标目录")
            leftovers = [item.name for item in packs.iterdir()]
            self.assertEqual(leftovers, [], f"临时目录没清干净：{leftovers}")

    def test_successful_copy_is_whole(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "某作品"
            (source / "games").mkdir(parents=True)
            (source / "games" / "a.txt").write_text("x", encoding="utf-8")
            packs = root / "packs"
            packs.mkdir()
            target = pack_import.copy_pack(source, packs)
            self.assertTrue((target / "games" / "a.txt").is_file())
            self.assertEqual([item.name for item in packs.iterdir()], ["某作品"])

    def test_existing_target_is_still_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "某作品"
            source.mkdir()
            packs = root / "packs"
            (packs / "某作品").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                pack_import.copy_pack(source, packs)


class LibraryUniqueIndexTest(unittest.TestCase):
    """数据库层的部分唯一索引要真的挡住并发重复插入。"""

    def test_unique_index_rejects_second_live_row(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            item = library.save("作品", "角色A", "校服", "a0001", "normal", _sprite(1))
            db = library.root / "library.sqlite3"
            connection = sqlite3.connect(db)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    with connection:
                        connection.execute(
                            "INSERT INTO sprites (id, game, character, body, face, category, "
                            "relative_path, width, height, saved_at, content_hash, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            ("f" * 32, "作品", "角色A", "校服", "a0001", "normal",
                             "images/ff/x.png", 1, 1, "2026-01-01T00:00:00+08:00",
                             item["contentHash"] if "contentHash" in item else _hash_of(library, item["id"]),
                             "2026-01-01T00:00:00+08:00"),
                        )
            finally:
                connection.close()


def _hash_of(library: SpriteLibrary, item_id: str) -> str:
    connection = sqlite3.connect(library.root / "library.sqlite3")
    try:
        return connection.execute("SELECT content_hash FROM sprites WHERE id = ?", (item_id,)).fetchone()[0]
    finally:
        connection.close()


class ConcurrentSaveTest(unittest.TestCase):
    """并发保存同一张图，库里只能有一条（不是各插一条）。"""

    def test_concurrent_saves_collapse_to_one_row(self):
        import threading

        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            image = _sprite(7)
            barrier = threading.Barrier(4)
            outcomes: list[bool] = []
            lock = threading.Lock()

            def worker():
                barrier.wait()
                try:
                    result = library.save("作品", "角色A", "校服", "a0001", "normal", image)
                    with lock:
                        outcomes.append(bool(result["created"]))
                except Exception as error:
                    with lock:
                        errors.append(repr(error))

            errors: list[str] = []
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [], f"并发保存不该抛异常：{errors}")
            self.assertEqual(sum(outcomes), 1,
                             f"并发入库应只新建 1 条，实际 {sum(outcomes)} 条：{outcomes}")
            self.assertEqual(library.list(False)["total"], 1)


class PbdSizeCapTest(unittest.TestCase):
    """验证 PBD 文件上限与本地样本余量。"""

    def test_cap_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "oversized.pbd"
            source.write_bytes(bytes(1025))
            with patch.object(pbd_parser, "MAX_PBD_BYTES", 1024):
                with self.assertRaises(ValueError):
                    pbd_parser.read_pbd(source)

    def test_real_assets_have_plenty_of_headroom(self):
        samples = list((Path(__file__).resolve().parents[1] / "sprite-packs").rglob("*.pbd"))
        if not samples:
            self.skipTest("未提供本地 PBD 样本")
        biggest = max(path.stat().st_size for path in samples)
        self.assertLess(biggest * 10, pbd_parser.MAX_PBD_BYTES,
                        "真实 .pbd 离上限太近了，有误拦风险")


if __name__ == "__main__":
    unittest.main()
