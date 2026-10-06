import ctypes
import tempfile
import unittest
from pathlib import Path

import windows_file_drag


class WindowsFileDragTest(unittest.TestCase):
    def test_hdrop_contains_unicode_absolute_file_path(self):
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        shell32.DragQueryFileW.restype = ctypes.c_uint
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "测试立绘.png"
            path.write_bytes(b"png")
            handle = windows_file_drag.create_hdrop([path])
            try:
                self.assertEqual(shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0), 1)
                length = shell32.DragQueryFileW(handle, 0, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, 0, buffer, len(buffer))
                self.assertEqual(Path(buffer.value), path.resolve())
            finally:
                windows_file_drag.kernel32.GlobalFree(handle)

    def test_data_object_offers_cf_hdrop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sprite.png"
            path.write_bytes(b"png")
            data = windows_file_drag.FileDataObject(path)
            format_value = windows_file_drag.FORMATETC(
                windows_file_drag.CF_HDROP, None, windows_file_drag.DVASPECT_CONTENT,
                -1, windows_file_drag.TYMED_HGLOBAL,
            )
            medium = windows_file_drag.STGMEDIUM()
            result = data.callbacks[3](data.pointer, ctypes.byref(format_value), ctypes.byref(medium))
            self.assertEqual(result, windows_file_drag.S_OK)
            self.assertEqual(medium.tymed, windows_file_drag.TYMED_HGLOBAL)
            windows_file_drag.ole32.ReleaseStgMedium(ctypes.byref(medium))

            interface = ctypes.c_void_p()
            result = data.callbacks[0](data.pointer, ctypes.byref(windows_file_drag.IID_IDATAOBJECT),
                                       ctypes.byref(interface))
            self.assertEqual(result, windows_file_drag.S_OK)
            self.assertEqual(interface.value, data.pointer.value)
            data.callbacks[2](data.pointer)

    def test_drop_source_cancels_or_drops_on_standard_gestures(self):
        source = windows_file_drag.FileDropSource()
        continue_drag = source.callbacks[3]
        self.assertEqual(continue_drag(source.pointer, False, windows_file_drag.MK_LBUTTON),
                         windows_file_drag.S_OK)
        self.assertEqual(continue_drag(source.pointer, False, 0), windows_file_drag.DRAGDROP_S_DROP)
        self.assertEqual(continue_drag(source.pointer, True, windows_file_drag.MK_LBUTTON),
                         windows_file_drag.DRAGDROP_S_CANCEL)


if __name__ == "__main__":
    unittest.main()
