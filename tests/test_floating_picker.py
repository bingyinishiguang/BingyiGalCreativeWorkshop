import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from PIL import Image

from floating_picker import FloatingPicker, query_library_items
from sprite_library import SpriteLibrary


class FloatingPickerTest(unittest.TestCase):
    def test_query_uses_normal_partition_search_and_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            image = Image.new("RGBA", (12, 20), (0, 0, 0, 0))
            image.putpixel((6, 10), (10, 20, 30, 255))
            normal = library.save("作品", "普通角色", "校服", "a0001", "normal", image)
            library.save("作品", "特殊角色", "泳衣", "a0001", "swimwear", image)
            library.update(normal["id"], False, "常用微笑", "", True, ["开心"])

            self.assertEqual(len(query_library_items(library)), 1)
            self.assertEqual(query_library_items(library, "开心")[0]["id"], normal["id"])
            self.assertEqual(query_library_items(library, favorites=True)[0]["id"], normal["id"])
            self.assertEqual(query_library_items(library, "特殊角色"), [])

    def test_window_renders_library_and_collapses(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            image = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
            image.putpixel((20, 40), (30, 40, 50, 255))
            library.save("作品", "角色", "校服", "a0001", "normal", image)
            root = tk.Tk()
            root.withdraw()
            try:
                picker = FloatingPicker(root, library)
                root.update_idletasks()
                self.assertEqual(len(picker.items), 1)
                self.assertIsNotNone(picker.preview_photo)
                self.assertTrue(bool(root.attributes("-topmost")))
                picker.toggle_collapsed()
                self.assertTrue(picker.collapsed)
                self.assertEqual(picker.content.winfo_manager(), "")
                picker.toggle_collapsed()
                self.assertEqual(picker.content.winfo_manager(), "pack")
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
