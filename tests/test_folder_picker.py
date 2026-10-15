import ctypes
import os
import pytest
from types import SimpleNamespace
from app_settings import browse_for_directory

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native folder picker")

class NativeCall:
    def __init__(self, call): self.call = call
    def __call__(self, *args): return self.call(*args)

def test_initial_folder_only_selects_without_restricting_root(monkeypatch):
    observed = {}
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
    def browse(pointer):
        info = pointer._obj
        observed['root'] = info.pidlRoot
        callback_type(info.lpfn)(0, 1, None, None)
        return 42
    def send(hwnd, message, by_path, pointer):
        observed.update(message=message, by_path=by_path, initial=ctypes.wstring_at(pointer))
        return 0
    def selected(pidl, buffer):
        buffer.value = 'F:\\自由选择\\剪映草稿'
        return True
    freed = []
    fake = SimpleNamespace(
        ole32=SimpleNamespace(OleInitialize=NativeCall(lambda _: 0), OleUninitialize=NativeCall(lambda: observed.update(uninitialized=True)), CoTaskMemFree=NativeCall(freed.append)),
        shell32=SimpleNamespace(SHBrowseForFolderW=NativeCall(browse), SHGetPathFromIDListW=NativeCall(selected)),
        user32=SimpleNamespace(SendMessageW=NativeCall(send)))
    monkeypatch.setattr(ctypes, 'windll', fake)
    assert browse_for_directory('选择草稿目录', 'C:\\默认目录') == 'F:\\自由选择\\剪映草稿'
    assert observed == {'root': None, 'message': 0x467, 'by_path': 1, 'initial': 'C:\\默认目录', 'uninitialized': True}
    assert freed == [42]

def test_folder_picker_cancel(monkeypatch):
    fake = SimpleNamespace(
        ole32=SimpleNamespace(OleInitialize=NativeCall(lambda _: 0), OleUninitialize=NativeCall(lambda: None), CoTaskMemFree=NativeCall(lambda _: None)),
        shell32=SimpleNamespace(SHBrowseForFolderW=NativeCall(lambda _: None), SHGetPathFromIDListW=NativeCall(lambda *_: False)),
        user32=SimpleNamespace(SendMessageW=NativeCall(lambda *_: 0)))
    monkeypatch.setattr(ctypes, 'windll', fake)
    assert browse_for_directory('选择草稿目录') == ''


def test_folder_picker_reports_initialization_failure(monkeypatch):
    fake=SimpleNamespace(ole32=SimpleNamespace(OleInitialize=NativeCall(lambda _: -2147417850)),shell32=SimpleNamespace())
    monkeypatch.setattr(ctypes, 'windll', fake)
    with pytest.raises(RuntimeError, match='初始化失败'):
        browse_for_directory()
