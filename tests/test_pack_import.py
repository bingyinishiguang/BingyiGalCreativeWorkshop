"""pack_import 测试：格式校验、复制导入（只新增）、链接登记/移除、合并去重。"""
import tempfile
import unittest
from pathlib import Path

import pack_import


def make_pack(root: Path, name: str, with_pbd: bool = True) -> Path:
    pack = root / name / "games" / "某作品" / "角色A"
    pack.mkdir(parents=True)
    if with_pbd:
        (pack / "a.pbd").write_bytes(b"fake")
    (pack / "a.txt").write_text("x,y", encoding="utf-8")
    return root / name


class PackImportTest(unittest.TestCase):
    def test_analyze_valid_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp) / "sprite-packs"
            packs.mkdir()
            pack = make_pack(Path(tmp), "测试包")
            result = pack_import.analyze(str(pack), packs)
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.pack_name, "测试包")
            self.assertGreaterEqual(result.pbd_count, 1)

    def test_analyze_rejects_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp) / "sprite-packs"
            packs.mkdir()
            empty = Path(tmp) / "空目录"
            empty.mkdir()
            result = pack_import.analyze(str(empty), packs)
            self.assertFalse(result.ok)

    def test_analyze_rejects_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp) / "sprite-packs"
            (packs / "测试包").mkdir(parents=True)
            src = make_pack(Path(tmp) / "src", "测试包")
            result = pack_import.analyze(str(src), packs)
            self.assertFalse(result.ok)
            self.assertTrue(any("已存在" in e for e in result.errors))

    def test_copy_pack_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp) / "sprite-packs"
            packs.mkdir()
            src = make_pack(Path(tmp), "测试包")
            target = pack_import.copy_pack(src, packs)
            self.assertTrue((target / "games" / "某作品" / "角色A" / "a.pbd").exists())
            with self.assertRaises(FileExistsError):
                pack_import.copy_pack(src, packs)

    def test_link_add_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            links = Path(tmp) / "pack-links.json"
            src = make_pack(Path(tmp), "外链包")
            entry = pack_import.add_link(links, src)
            self.assertEqual(entry["name"], "外链包")

            pack_import.add_link(links, src)
            self.assertEqual(len(pack_import.load_links(links)), 1)
            self.assertTrue(pack_import.remove_link(links, "外链包"))
            self.assertFalse(pack_import.remove_link(links, "外链包"))

    def test_iter_pack_roots_merges_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp) / "sprite-packs"
            packs.mkdir()
            make_pack(packs.parent, "内置包")
            builtin = packs / "内置包"
            (builtin / "games").mkdir(parents=True)
            links = Path(tmp) / "pack-links.json"
            ext = make_pack(Path(tmp), "外链包")
            pack_import.add_link(links, ext)

            dup = make_pack(Path(tmp), "dup") / "x"
            roots = pack_import.iter_pack_roots(packs, links)
            names = [n for n, _p, _s in roots]
            self.assertIn("内置包", names)
            self.assertIn("外链包", names)
            sources = {n: s for n, _p, s in roots}
            self.assertEqual(sources["内置包"], "builtin")
            self.assertEqual(sources["外链包"], "link")


if __name__ == "__main__":
    unittest.main()
