"""以 ctypes 调用 Win32 文件选择框，支持服务工作线程与多选。"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

#GetOpenFileNameW 的 Flags
OFN_READONLY = 0x00000001
OFN_HIDEREADONLY = 0x00000004
OFN_NOCHANGEDIR = 0x00000008  #关键：不许它改进程当前目录
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_ALLOWMULTISELECT = 0x00000200
OFN_EXPLORER = 0x00080000

IMAGE_FILTER = (
    "图片文件\0*.png;*.jpg;*.jpeg;*.webp;*.bmp\0"
    "PNG\0*.png\0"
    "JPEG\0*.jpg;*.jpeg\0"
    "WebP\0*.webp\0"
    "BMP\0*.bmp\0"
    "所有文件\0*.*\0\0"
)


ZIP_FILTER = (
    "素材包压缩包\0*.zip\0"
    "ZIP\0*.zip\0"
    "所有文件\0*.*\0\0"
)


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = (
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    )


def _split_multi(buffer: str) -> list[str]:
    """解析 NUL 分隔缓冲区：单选为完整路径，多选为目录与文件名列表。"""
    #空段之后是缓冲区尾部没有意义的残留数据，先切掉。
    head = buffer.split("\0\0", 1)[0]
    parts = [part for part in head.split("\0") if part]
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0]]
    directory = parts[0]
    return [os.path.join(directory, name) for name in parts[1:]]


def browse_for_images(title: str = "选择要导入的立绘图片", initial_dir: str | None = None, *, file_filter: str | None = None) -> list[str]:
    """弹出系统多选文件框，返回所选图片的绝对路径列表（取消/失败返回空列表）。"""
    if os.name != "nt":
        return []
    try:
        comdlg32 = ctypes.windll.comdlg32
        buffer_size = 65536
        buffer = ctypes.create_unicode_buffer(buffer_size)
        #初始目录写进缓冲（GetOpenFileNameW 的用法），不传 lpstrInitialDir 以免旧系统忽略
        if initial_dir and os.path.isdir(initial_dir):
            buffer.value = initial_dir

        flags = (OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_FILEMUSTEXIST
                 | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_NOCHANGEDIR)
        info = _OPENFILENAMEW()
        info.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
        info.hwndOwner = None
        info.lpstrFilter = file_filter or IMAGE_FILTER
        info.nFilterIndex = 1
        info.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
        info.nMaxFile = buffer_size
        info.lpstrTitle = title
        info.Flags = flags

        comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
        comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
        if not comdlg32.GetOpenFileNameW(ctypes.byref(info)):
            #用户取消，或对话框创建失败：统一当「没选东西」处理，不抛异常。
            return []
        #读取原始缓冲区；.value 会在首个 NUL 截断多选结果。
        raw = ctypes.string_at(
            ctypes.addressof(buffer), buffer_size * ctypes.sizeof(ctypes.c_wchar)
        )
        resolved = _split_multi(raw.decode("utf-16-le", "replace"))
        #兜底：解析结果里若混进目录（例如解析异常），在这里就挡掉，
        #而不是让后端给出看不懂的"不是支持的图片格式"。
        return [item for item in resolved if os.path.isfile(item)]
    except Exception:
        return []


def browse_for_zip(title: str = "选择素材包压缩包（.zip）", initial_dir: str | None = None) -> str:
    """弹出系统单选文件框选择 zip 素材包；取消/失败返回空字符串。"""
    paths = browse_for_images(title, initial_dir, file_filter=ZIP_FILTER)
    return paths[0] if paths else ""


def browse_for_backgrounds() -> list[str]:
    return browse_for_images('选择背景图片或视频', file_filter=(
        '背景图片与视频\0*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v\0'
        '图片\0*.png;*.jpg;*.jpeg;*.webp;*.bmp\0'
        '视频\0*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v\0\0'))
