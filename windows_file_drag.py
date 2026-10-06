from __future__ import annotations

import ctypes
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path


if sys.platform != "win32":
    raise RuntimeError("原生文件拖放只支持 Windows")


HRESULT = ctypes.c_long
ULONG = wintypes.ULONG
DWORD = wintypes.DWORD
BOOL = wintypes.BOOL
LONG = wintypes.LONG

S_OK = 0
S_FALSE = 1
E_NOINTERFACE = -2147467262
E_NOTIMPL = -2147467263
DV_E_FORMATETC = -2147221404
OLE_E_ADVISENOTSUPPORTED = -2147221501
DATA_S_SAMEFORMATETC = 0x00040130
DRAGDROP_S_DROP = 0x00040100
DRAGDROP_S_CANCEL = 0x00040101
DRAGDROP_S_USEDEFAULTCURSORS = 0x00040102
RPC_E_CHANGED_MODE = -2147417850

CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DATADIR_GET = 1
MK_LBUTTON = 0x0001
DROPEFFECT_COPY = 0x0001
GHND = 0x0042


class DroppedOnForbiddenTarget(RuntimeError):
    """拖放被取消：落点在桌面/资源管理器等禁止目标上。"""


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> GUID:
        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", DWORD),
        ("lindex", LONG),
        ("tymed", DWORD),
    ]


class _STGMEDIUM_VALUE(ctypes.Union):
    _fields_ = [
        ("hBitmap", ctypes.c_void_p),
        ("hMetaFilePict", ctypes.c_void_p),
        ("hEnhMetaFile", ctypes.c_void_p),
        ("hGlobal", ctypes.c_void_p),
        ("lpszFileName", ctypes.c_wchar_p),
        ("pstm", ctypes.c_void_p),
        ("pstg", ctypes.c_void_p),
    ]


class STGMEDIUM(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("tymed", DWORD),
        ("value", _STGMEDIUM_VALUE),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


QueryInterface = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
AddRef = ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)
Release = ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)
GetData = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))
GetDataHere = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))
QueryGetData = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC))
GetCanonicalFormatEtc = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(FORMATETC))
SetData = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM), BOOL)
EnumFormatEtc = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, DWORD, ctypes.POINTER(ctypes.c_void_p))
DAdvise = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), DWORD, ctypes.c_void_p, ctypes.POINTER(DWORD))
DUnadvise = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, DWORD)
EnumDAdvise = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
QueryContinueDrag = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, BOOL, DWORD)
GiveFeedback = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, DWORD)


class IDataObjectVTable(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", QueryInterface), ("AddRef", AddRef), ("Release", Release),
        ("GetData", GetData), ("GetDataHere", GetDataHere), ("QueryGetData", QueryGetData),
        ("GetCanonicalFormatEtc", GetCanonicalFormatEtc), ("SetData", SetData),
        ("EnumFormatEtc", EnumFormatEtc), ("DAdvise", DAdvise),
        ("DUnadvise", DUnadvise), ("EnumDAdvise", EnumDAdvise),
    ]


class IDropSourceVTable(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", QueryInterface), ("AddRef", AddRef), ("Release", Release),
        ("QueryContinueDrag", QueryContinueDrag), ("GiveFeedback", GiveFeedback),
    ]


class _IDataObjectInstance(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IDataObjectVTable)), ("ref_count", ULONG)]


class _IDropSourceInstance(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IDropSourceVTable)), ("ref_count", ULONG)]


ole32 = ctypes.OleDLL("ole32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
GA_ROOT = 2
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p

ole32.OleInitialize.argtypes = [ctypes.c_void_p]
ole32.OleInitialize.restype = HRESULT
ole32.OleUninitialize.argtypes = []
ole32.DoDragDrop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
ole32.DoDragDrop.restype = HRESULT
ole32.ReleaseStgMedium.argtypes = [ctypes.POINTER(STGMEDIUM)]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
shell32.SHCreateStdEnumFmtEtc.argtypes = [wintypes.UINT, ctypes.POINTER(FORMATETC), ctypes.POINTER(ctypes.c_void_p)]
shell32.SHCreateStdEnumFmtEtc.restype = HRESULT


IID_IUNKNOWN = GUID.parse("00000000-0000-0000-c000-000000000046")
IID_IDATAOBJECT = GUID.parse("0000010e-0000-0000-c000-000000000046")
IID_IDROPSOURCE = GUID.parse("00000121-0000-0000-c000-000000000046")


def _guid_equal(left: ctypes.POINTER(GUID), right: GUID) -> bool:
    return ctypes.string_at(left, ctypes.sizeof(GUID)) == bytes(right)


def _instance(this: ctypes.c_void_p, kind):
    return ctypes.cast(this, ctypes.POINTER(kind)).contents


def _add_ref(this: ctypes.c_void_p, kind) -> int:
    pointer = ctypes.cast(this, ctypes.POINTER(kind))
    pointer.contents.ref_count += 1
    return pointer.contents.ref_count


def _release(this: ctypes.c_void_p, kind) -> int:
    pointer = ctypes.cast(this, ctypes.POINTER(kind))
    if pointer.contents.ref_count:
        pointer.contents.ref_count -= 1
    return pointer.contents.ref_count


def create_hdrop(paths: list[Path]) -> ctypes.c_void_p:
    resolved = [str(path.resolve()) for path in paths]
    if not resolved or any(not Path(path).is_file() for path in resolved):
        raise FileNotFoundError("拖放文件不存在")
    names = ("\0".join(resolved) + "\0\0").encode("utf-16le")
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    payload = header + names
    handle = kernel32.GlobalAlloc(GHND, len(payload))
    if not handle:
        raise MemoryError("无法为文件拖放分配内存")
    address = kernel32.GlobalLock(handle)
    if not address:
        kernel32.GlobalFree(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        ctypes.memmove(address, payload, len(payload))
    finally:
        kernel32.GlobalUnlock(handle)
    return handle


class FileDataObject:
    def __init__(self, path: Path):
        self.path = path.resolve()

        @QueryInterface
        def query_interface(this, iid, output):
            if _guid_equal(iid, IID_IUNKNOWN) or _guid_equal(iid, IID_IDATAOBJECT):
                output[0] = this
                _add_ref(this, _IDataObjectInstance)
                return S_OK
            output[0] = None
            return E_NOINTERFACE

        @AddRef
        def add_ref(this):
            return _add_ref(this, _IDataObjectInstance)

        @Release
        def release(this):
            return _release(this, _IDataObjectInstance)

        @GetData
        def get_data(this, format_pointer, medium_pointer):
            format_value = format_pointer.contents
            if (format_value.cfFormat != CF_HDROP or format_value.dwAspect != DVASPECT_CONTENT
                    or not format_value.tymed & TYMED_HGLOBAL):
                return DV_E_FORMATETC
            handle = create_hdrop([self.path])
            medium_pointer.contents.tymed = TYMED_HGLOBAL
            medium_pointer.contents.hGlobal = handle
            medium_pointer.contents.pUnkForRelease = None
            return S_OK

        @GetDataHere
        def get_data_here(this, format_pointer, medium_pointer):
            return E_NOTIMPL

        @QueryGetData
        def query_get_data(this, format_pointer):
            format_value = format_pointer.contents
            if (format_value.cfFormat == CF_HDROP and format_value.dwAspect == DVASPECT_CONTENT
                    and format_value.tymed & TYMED_HGLOBAL):
                return S_OK
            return DV_E_FORMATETC

        @GetCanonicalFormatEtc
        def get_canonical(this, source, destination):
            destination.contents.ptd = None
            return DATA_S_SAMEFORMATETC

        @SetData
        def set_data(this, format_pointer, medium_pointer, release_medium):
            return E_NOTIMPL

        @EnumFormatEtc
        def enum_formats(this, direction, output):
            if direction != DATADIR_GET:
                output[0] = None
                return E_NOTIMPL
            format_value = FORMATETC(CF_HDROP, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
            return shell32.SHCreateStdEnumFmtEtc(1, ctypes.byref(format_value), output)

        @DAdvise
        def advise(this, format_pointer, flags, sink, connection):
            return OLE_E_ADVISENOTSUPPORTED

        @DUnadvise
        def unadvise(this, connection):
            return OLE_E_ADVISENOTSUPPORTED

        @EnumDAdvise
        def enum_advise(this, output):
            output[0] = None
            return OLE_E_ADVISENOTSUPPORTED

        self.callbacks = (query_interface, add_ref, release, get_data, get_data_here,
                          query_get_data, get_canonical, set_data, enum_formats,
                          advise, unadvise, enum_advise)
        self.vtable = IDataObjectVTable(*self.callbacks)
        self.instance = _IDataObjectInstance(ctypes.pointer(self.vtable), 1)

    @property
    def pointer(self) -> ctypes.c_void_p:
        return ctypes.cast(ctypes.pointer(self.instance), ctypes.c_void_p)


class FileDropSource:
    def __init__(self, forbidden_check=None):
        self.cancelled_on_forbidden = False
        @QueryInterface
        def query_interface(this, iid, output):
            if _guid_equal(iid, IID_IUNKNOWN) or _guid_equal(iid, IID_IDROPSOURCE):
                output[0] = this
                _add_ref(this, _IDropSourceInstance)
                return S_OK
            output[0] = None
            return E_NOINTERFACE

        @AddRef
        def add_ref(this):
            return _add_ref(this, _IDropSourceInstance)

        @Release
        def release(this):
            return _release(this, _IDropSourceInstance)

        @QueryContinueDrag
        def continue_drag(this, escape_pressed, key_state):
            if escape_pressed:
                return DRAGDROP_S_CANCEL
            if not key_state & MK_LBUTTON:
                #松手即将触发 Drop：先检查落点，命中禁止目标则取消，阻止文件被复制
                if forbidden_check is not None and forbidden_check():
                    self.cancelled_on_forbidden = True
                    return DRAGDROP_S_CANCEL
                return DRAGDROP_S_DROP
            return S_OK

        @GiveFeedback
        def give_feedback(this, effect):
            return DRAGDROP_S_USEDEFAULTCURSORS

        self.callbacks = (query_interface, add_ref, release, continue_drag, give_feedback)
        self.vtable = IDropSourceVTable(*self.callbacks)
        self.instance = _IDropSourceInstance(ctypes.pointer(self.vtable), 1)

    @property
    def pointer(self) -> ctypes.c_void_p:
        return ctypes.cast(ctypes.pointer(self.instance), ctypes.c_void_p)


def default_drag_dir() -> Path:
    """使用数据目录下的稳定拖出路径；目标编辑器会长期按该路径引用媒体。"""
    try:
        import app_paths

        return app_paths.resolve_data_dir() / "exports" / app_paths.DRAG_OUT_DIR_NAME
    except Exception:
        #极端情况下（导入失败）退回临时目录，保证拖放本身仍然可用
        return Path(tempfile.gettempdir()) / "BingyiGalCreativeWorkshop-DragOut"


#当前拖出目录。调用方（桌宠/取用窗）在启动时用 set_drag_dir() 注入用户设置里的位置。
DRAG_COPY_DIR = default_drag_dir()


def set_drag_dir(directory: Path | str | None) -> Path:
    """设置拖出目录（None 或空 = 用默认位置），返回实际生效的目录。"""
    global DRAG_COPY_DIR
    text = str(directory or "").strip()
    DRAG_COPY_DIR = Path(text) if text else default_drag_dir()
    return DRAG_COPY_DIR


def migrate_drag_dir(old: Path | None, new: Path) -> int:
    """迁移拖出副本并保留旧目录；目标编辑器需要重新链接媒体。"""
    if old is None:
        return 0
    old_path = Path(old)
    new_path = Path(new)
    if old_path == new_path or not old_path.is_dir():
        return 0
    new_path.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in old_path.iterdir():
        target = new_path / child.name
        if target.exists():
            continue
        try:
            shutil.move(str(child), str(target))
            moved += 1
        except OSError:
            continue
    return moved


def clear_drag_dir(directory: Path | None = None) -> int:
    """按显式请求清理拖出副本；已引用这些文件的工程会需要重新链接。"""
    target = Path(directory) if directory else DRAG_COPY_DIR
    if not target.is_dir():
        return 0
    removed = 0
    for child in target.iterdir():
        if not child.is_file():
            continue
        try:
            child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def sprite_filename(item: dict) -> str:
    """按名称、角色、首个标签和表情生成文件名，移除 Windows 非法字符。"""
    base = str(item.get("displayName") or item.get("character") or "立绘").strip()
    parts = [part for part in (base, *(item.get("tags") or [])[:1],
                               str(item.get("face") or "").strip()) if part]
    name = "_".join(dict.fromkeys(parts))
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" ._")
    return (name or "立绘")[:80]


#按路径记录删除计划与文件指纹；复用前取消旧计划，删除前核对指纹。
_PENDING_DELETES: dict[str, tuple[threading.Timer, tuple[int, int] | None]] = {}
_PENDING_LOCK = threading.Lock()


def _file_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _cancel_pending_delete(target: Path) -> None:
    """取消某路径上尚在等待的删除（复用它之前必须调用）。"""
    with _PENDING_LOCK:
        entry = _PENDING_DELETES.pop(str(target), None)
    if entry is not None:
        entry[0].cancel()


def make_draggable_copy(path: Path, wanted_name: str) -> Path:
    """在稳定目录生成可读文件名的 PNG 副本；复用路径时取消旧删除计划。"""
    directory = DRAG_COPY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", wanted_name).strip(" ._") or "立绘"
    target = directory / f"{safe_name}.png"
    #复用固定名之前，先撤销"上一次没投出去"遗留的删除计划，
    #否则它会在几秒后把这次成功投放的文件删掉。
    _cancel_pending_delete(target)
    shutil.copyfile(Path(path), target)
    return target


def cleanup_drag_copy(path: Path | None, dropped: bool, delay_seconds: float = 10.0) -> None:
    """仅清理取消或无效投放的副本，成功投放的媒体路径持续保留。"""
    if path is None or dropped:
        return

    def _delete() -> None:
        with _PENDING_LOCK:
            entry = _PENDING_DELETES.pop(str(path), None)
        #指纹核对：如果这一份已经被后来的拖拽覆盖过（内容/时间变了），
        #说明它现在是"用户成功投放的那一份"，绝不能删。
        if entry is not None and entry[1] is not None:
            if _file_fingerprint(path) != entry[1]:
                return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    #没投出去：目标应用根本没拿到文件，可以立刻删。
    if delay_seconds <= 0:
        _delete()
        return
    timer = threading.Timer(delay_seconds, _delete)
    timer.daemon = True
    with _PENDING_LOCK:
        previous = _PENDING_DELETES.get(str(path))
        if previous is not None:
            previous[0].cancel()
        _PENDING_DELETES[str(path)] = (timer, _file_fingerprint(path))
    timer.start()


def _window_class_at_cursor() -> str:
    """返回当前鼠标光标所在顶层窗口的类名；失败返回空串。"""
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return ""
    handle = user32.WindowFromPoint(point)
    if not handle:
        return ""
    root = user32.GetAncestor(handle, GA_ROOT)
    if root:
        handle = root
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(handle, buffer, len(buffer))
    return buffer.value if length else ""


def _dropped_on_desktop_or_explorer() -> bool:
    """按顶层窗口类识别桌面与资源管理器落点，避免子窗口漏判。"""
    return _window_class_at_cursor() in {"Progman", "WorkerW", "CabinetWClass", "ExploreWClass"}


def drag_file(path: Path) -> bool:
    file_path = path.resolve()
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    initialized = ole32.OleInitialize(None)
    if initialized not in (S_OK, S_FALSE, RPC_E_CHANGED_MODE):
        raise OSError(f"OLE 初始化失败：0x{initialized & 0xffffffff:08x}")
    if initialized == RPC_E_CHANGED_MODE:
        raise RuntimeError("当前线程的 Windows 拖放环境不可用")
    try:
        data = FileDataObject(file_path)
        source = FileDropSource(forbidden_check=_dropped_on_desktop_or_explorer)
        effect = DWORD(0)
        result = ole32.DoDragDrop(data.pointer, source.pointer, DROPEFFECT_COPY, ctypes.byref(effect))
        if result == DRAGDROP_S_CANCEL:
            if source.cancelled_on_forbidden:
                raise DroppedOnForbiddenTarget("不能拖到桌面或文件夹，请拖到剪映素材区")
            return False
        if result != DRAGDROP_S_DROP:
            raise OSError(f"Windows 拖放失败：0x{result & 0xffffffff:08x}")
        if _dropped_on_desktop_or_explorer():
            raise DroppedOnForbiddenTarget("不能拖到桌面或文件夹，请拖到剪映素材区")
        return bool(effect.value & DROPEFFECT_COPY)
    finally:
        ole32.OleUninitialize()
