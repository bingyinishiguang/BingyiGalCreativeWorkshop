import csv
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from sprite_composer import (
    IsolationPolicy,
    discover_pack_game_roots,
    exports_root,
    expression_preview,
    game_directories,
    run_custom_batch,
    scan_characters,
    scan_lime_poses,
    validate_custom_batch,
    web_catalog,
)
from txt_parser import scan_txt_library


class CustomBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        roots = discover_pack_game_roots(root)
        games = game_directories(roots)
        if not {"常轨脱离", "LimeLightLemonadeJam"} <= games.keys():
            raise unittest.SkipTest("未提供三种适配器的本地素材")
        cls.characters = scan_characters(games["常轨脱离"])
        cls.lime = scan_lime_poses(games["LimeLightLemonadeJam"])
        cls.txt = {}
        for pack_root in roots:
            found, warnings = scan_txt_library(pack_root)
            if warnings:
                raise AssertionError(warnings[:3])
            cls.txt.update(found)
        if not any(name not in {"常轨脱离", "LimeLightLemonadeJam"} for name in cls.txt):
            raise unittest.SkipTest("未提供 TXT 适配器的本地素材")
        cls.catalog = web_catalog(cls.characters, cls.lime, cls.txt)

    def examples(self):
        results = []
        for game_name in ("常轨脱离", "LimeLightLemonadeJam"):
            results.append(self.first_normal(game_name))
        txt_game = next(name for name in self.txt if name not in ("常轨脱离", "LimeLightLemonadeJam"))
        results.append(self.first_normal(txt_game))
        return results

    def first_normal(self, game_name):
        for character_name, character in self.catalog[game_name]["characters"].items():
            for body, faces in character["bodies"].items():
                if character["bodyCategories"][body] == "normal" and faces:
                    return {"game": game_name, "character": character_name, "body": body, "face": faces[0]}
        raise AssertionError(f"没有普通组合：{game_name}")

    def test_three_adapters_and_alpha_padding(self):
        items = validate_custom_batch(self.examples(), self.catalog)
        output_root = exports_root(Path(__file__).resolve().parents[1])
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as parent:
            output = Path(parent) / "batch-test"
            job = {"state": "running", "total": 3, "completed": 0, "succeeded": 0, "errors": [], "current": ""}
            run_custom_batch(items, output, job, threading.Lock(), self.characters, self.lime, self.txt)
            self.assertEqual(job["state"], "finished", job["errors"])
            self.assertEqual(job["succeeded"], 3, job["errors"])
            with (output / "batch-manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(row["状态"], "成功")
                with Image.open(output / row["输出文件"]) as image:
                    self.assertEqual(image.mode, "RGBA")
                    box = image.getbbox()
                    self.assertIsNotNone(box)
                    self.assertGreaterEqual(box[0], 4)
                    self.assertGreaterEqual(box[1], 4)
                    self.assertGreaterEqual(image.width - box[2], 4)
                    self.assertGreaterEqual(image.height - box[3], 4)

    def test_rejects_duplicate_and_special(self):
        item = self.examples()[0]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_custom_batch([item, item], self.catalog)
        with self.assertRaisesRegex(ValueError, "普通|不存在"):
            validate_custom_batch([{"game": "常轨脱离", "character": "圣莉莉子", "body": "rir_noa0000", "face": "a0001"}], self.catalog)

    def test_expression_previews_from_three_adapters(self):
        for item in self.examples():
            with self.subTest(game=item["game"]):
                preview = expression_preview(item["game"], item["character"], item["body"], item["face"],
                                             640, self.characters, self.lime, self.txt)
                self.assertEqual(preview.mode, "RGBA")
                self.assertIsNotNone(preview.getbbox())
                self.assertLessEqual(max(preview.size), 640)
                self.assertLessEqual(abs(preview.width - preview.height), 2)


if __name__ == "__main__":
    unittest.main()
