import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app_settings import AppSettings
from sprite_composer import save_single_export

import app_paths


class AppSettingsTest(unittest.TestCase):
    def test_defaults_persistence_and_path_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "exports"
            batch.mkdir(parents=True)
            single = root.parent / f"bingyi-single-test-{root.name}"
            single.mkdir()
            try:
                settings = AppSettings(root, code_dir=root)

                self.assertEqual(settings.snapshot()["singleMode"], "folder")
                self.assertEqual(settings.batch_directory(), batch)

                self.assertEqual(settings.single_directory(), batch / "Single")
                values = {"singleMode": "folder", "singlePath": str(single), "batchPath": str(batch)}
                saved = settings.save(values)
                self.assertEqual(saved["singlePath"], str(single))
                self.assertEqual(AppSettings(root).single_directory(), single)
                self.assertEqual(AppSettings(root).batch_directory(), batch)
                if os.name == "nt":
                    with patch("app_settings.browse_for_directory", return_value=str(single)) as browse:
                        self.assertEqual(settings.choose_directory("single"), single)
                        browse.assert_called_once()
                self.assertEqual(settings.open_directory("library"), batch / "Library")
                with self.assertRaisesRegex(ValueError, "不存在"):
                    settings.save({**values, "singlePath": str(single / "missing")})
                self.assertEqual(settings.single_directory(), single)
                with self.assertRaisesRegex(ValueError, "原素材"):
                    settings.save({**values, "batchPath": str(root / "sprite-packs")})
                library = batch / "Library"
                library.mkdir(exist_ok=True)


                with self.assertRaisesRegex(ValueError, app_paths.LIBRARY_DIR_NAME):
                    settings.save({**values, "batchPath": str(library)})
            finally:
                single.rmdir()

    def test_single_export_unique_png_and_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            image = Image.new("RGBA", (30, 42), (0, 0, 0, 0))
            image.putpixel((15, 20), (30, 50, 90, 255))
            first = save_single_export(image, folder, "角色", "服装", "01")
            second = save_single_export(image, folder, "角色", "服装", "01")
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(folder.glob("*.png"))), 2)
            with Image.open(first) as saved:
                self.assertEqual(saved.mode, "RGBA")
                self.assertEqual(saved.getbbox(), (15, 20, 16, 21))


if __name__ == "__main__":
    unittest.main()
