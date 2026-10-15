import ctypes
import os
from types import SimpleNamespace

import pytest
import file_dialog

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows native file picker')


class Call:
    def __init__(self, fn): self.fn=fn
    def __call__(self,*args): return self.fn(*args)


@pytest.mark.parametrize('code,message', [(0,None),(0x3003,'文件过多'),(0xffff,'无法打开')])
def test_file_picker_separates_cancel_from_failure(monkeypatch,code,message):
    library=SimpleNamespace(GetOpenFileNameW=Call(lambda *_:False),CommDlgExtendedError=Call(lambda:code))
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(comdlg32=library))
    if message:
        with pytest.raises(ValueError,match=message):file_dialog.browse_for_images()
    else:assert file_dialog.browse_for_images()==[]


def test_file_picker_reports_native_exception(monkeypatch):
    def fail(*args):raise OSError('dialog unavailable')
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(comdlg32=SimpleNamespace(GetOpenFileNameW=Call(fail))))
    with pytest.raises(RuntimeError,match='系统文件选择失败'):file_dialog.browse_for_images()
