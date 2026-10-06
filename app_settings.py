from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path


class AppSettings:
    def __init__(self, data_dir: Path, code_dir: Path | None = None):
        import app_paths

        self.code_dir = (code_dir or app_paths.project_root()).resolve()
        self.data_dir = data_dir.resolve()
        self.default_batch = self.data_dir / "exports"
        self.default_single = self.default_batch / app_paths.SINGLE_EXPORT_DIR_NAME
        self.default_drag = self.default_batch / app_paths.DRAG_OUT_DIR_NAME
        self.library_dir = self.default_batch / app_paths.LIBRARY_DIR_NAME
        self.file = self.data_dir / app_paths.SETTINGS_NAME
        self.lock = threading.Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.was_reset = False
        if self.file.is_file():
            raw = None
            try:
                raw = self.file.read_text(encoding="utf-8")
            except OSError:
                #读取失败不等于文件损坏；保留设置文件，仅本次使用默认值。
                self.values = self._defaults()
            if raw is not None:
                try:
                    content = json.loads(raw)
                    if not isinstance(content, dict):
                        raise ValueError("设置文件格式不正确")
                    self.values = self._normalize(content)
                except Exception:
                    self._backup_broken_file()
                    self.values = self._defaults()
                    self.was_reset = True
        else:
            self.values = self._defaults()

    def _defaults(self) -> dict[str, str]:
        """单张导出默认保存到文件夹。"""
        return {"singleMode": "folder", "singlePath": "", "batchPath": "", "dragPath": ""}

    def _backup_broken_file(self) -> None:
        """把损坏的设置文件改名为 settings.json.broken-<时间戳>，保留现场供排查。"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.file.with_name(f"{self.file.name}.broken-{timestamp}")
            os.replace(self.file, backup)
        except Exception:
            pass

    def _normalize(self, values: dict) -> dict[str, str]:
        defaults = self._defaults()
        result: dict[str, str] = {}
        for key, fallback in defaults.items():
            raw = values.get(key) if isinstance(values, dict) else None
            result[key] = raw.strip() if isinstance(raw, str) else fallback
        if result["singleMode"] not in ("browser", "folder"):
            result["singleMode"] = defaults["singleMode"]
        for key in ("singlePath", "batchPath", "dragPath"):
            if len(result[key]) > 1000:
                result[key] = result[key][:1000]
        return result

    def _validate_directory(self, raw: str, title: str) -> Path:
        if not raw or not os.path.isabs(raw):
            raise ValueError(f"{title}必须填写已有文件夹的绝对路径")
        folder = Path(raw).resolve()
        if folder.parent == folder or folder == self.code_dir:
            raise ValueError(f"{title}请选择具体的子文件夹")
        if folder.is_relative_to(self.code_dir) and not folder.is_relative_to(self.default_batch):
            raise ValueError(f"{title}不能位于程序代码或原素材目录")
        if folder.is_relative_to(self.library_dir):
            raise ValueError(f"{title}不能位于立绘库（{self.library_dir.name}）内部")
        if not folder.is_dir():
            raise ValueError(f"{title}不存在，请先在资源管理器中新建文件夹")
        try:
            with tempfile.TemporaryFile(dir=folder):
                pass
        except OSError as error:
            raise ValueError(f"{title}不可写入：{error}") from error
        return folder

    def snapshot(self) -> dict[str, str]:
        with self.lock:
            values = dict(self.values)
            return {**values, "defaultBatchPath": str(self.default_batch),
                    "defaultSinglePath": str(self.default_single),
                    "defaultDragPath": str(self.default_drag),
                    "effectiveBatchPath": values["batchPath"] or str(self.default_batch),
                    "effectiveDragPath": values["dragPath"] or str(self.default_drag),
                    "libraryPath": str(self.library_dir),
                    "settingsReset": bool(getattr(self, "was_reset", False))}

    def save(self, values: dict) -> dict[str, str]:
        normalized = self._normalize(values)
        #单张保存目录留空是合法状态：表示用默认落盘目录（<数据目录>\exports\Single\）。
        if normalized["singleMode"] == "folder" and normalized["singlePath"]:
            self._validate_directory(normalized["singlePath"], "单张保存目录")
        if normalized["batchPath"]:
            self._validate_directory(normalized["batchPath"], "批量保存目录")
        old_drag = self.drag_directory()
        if normalized["dragPath"]:
            self._validate_directory(normalized["dragPath"], "拖出文件夹")
        temporary = self.data_dir / f"settings-{uuid.uuid4().hex}.tmp"
        with self.lock:
            try:
                payload = {**normalized, "schemaVersion": 1}
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.file)
                self.values = normalized
            finally:
                temporary.unlink(missing_ok=True)
        #拖出目录换位置：把已拖出的文件搬过去（旧目录保留）。剪映按路径引用旧文件，
        #所以调用方要把 movedDragFiles > 0 显示成"剪映里需要重新链接素材"。
        new_drag = self.drag_directory()
        moved = 0
        if old_drag != new_drag:
            try:
                import windows_file_drag

                moved = windows_file_drag.migrate_drag_dir(old_drag, new_drag)
            except Exception:
                moved = 0
        snapshot = self.snapshot()
        snapshot["movedDragFiles"] = str(moved)
        return snapshot

    def single_directory(self) -> Path:
        values = self.snapshot()
        if values["singleMode"] != "folder":
            raise ValueError("单张导出当前由浏览器管理")
        #留空 = 用默认落盘目录（<数据目录>\exports\Single\），而不是报错让用户先去设置。
        raw = values["singlePath"]
        if not raw:
            self.default_single.mkdir(parents=True, exist_ok=True)
            return self.default_single
        return self._validate_directory(raw, "单张保存目录")

    def batch_directory(self) -> Path:
        values = self.snapshot()
        return self._validate_directory(values["effectiveBatchPath"], "批量保存目录")

    def drag_directory(self) -> Path:
        """拖出文件的落点目录（剪映/PR 按路径引用它，所以必须稳定、不被自动清空）。"""
        values = self.snapshot()
        raw = values["dragPath"]
        target = Path(raw) if raw else self.default_drag
        target.mkdir(parents=True, exist_ok=True)
        return target

    def cleanup_drag_directory(self) -> int:
        """手动清空拖出目录，返回删除数量（默认永不自动删，见 windows_file_drag）。"""
        import windows_file_drag

        return windows_file_drag.clear_drag_dir(self.drag_directory())

    def open_directory(self, target: str) -> Path:
        if target == "library":
            self.library_dir.mkdir(parents=True, exist_ok=True)
            return self.library_dir
        if target == "batch":
            return self.batch_directory()
        if target == "single":
            return self.single_directory()
        if target == "drag":
            return self.drag_directory()
        raise ValueError("未知文件夹")

    def choose_directory(self, target: str) -> Path | None:
        if target not in ("single", "batch", "drag"):
            raise ValueError("未知保存类型")
        if os.name != "nt":
            raise ValueError("选择文件夹目前仅支持 Windows")

        values = self.snapshot()
        if target == "single":
            current = values["singlePath"]
        elif target == "batch":
            current = values["effectiveBatchPath"]
        else:
            current = values["effectiveDragPath"]
        initial = current if current and Path(current).is_dir() else str(self.default_batch)
        selected = browse_for_directory("选择保存文件夹", initial)
        if not selected:
            return None
        if target == "drag":
            #拖出目录必须是已存在且可写的目录；换位置时的搬运与"剪映需重新链接"的
            #提示由调用方负责（见 /api/settings 的 dragPath 处理）。
            return self._validate_directory(selected, "拖出文件夹")
        return self._validate_directory(selected, "保存目录")

    def choose_any_directory(self, title: str = "选择文件夹") -> str:
        """选择现有目录，不执行导出目录的写入校验；取消时返回空串。"""
        if os.name != "nt":
            return ""
        return browse_for_directory(title)


def browse_for_directory(title: str = "选择文件夹", initial: str | None = None) -> str:
    """通过 Win32 选择目录，允许从默认位置切换磁盘；取消时返回空串。"""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32

        ole32.OleInitialize.argtypes = [ctypes.c_void_p]
        ole32.OleInitialize.restype = ctypes.c_long
        try:
            ole32.OleInitialize(None)
        except Exception:
            pass

        class BrowseInfo(ctypes.Structure):
            _fields_ = (
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", ctypes.c_wchar_p),
                ("lpszTitle", ctypes.c_wchar_p),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            )

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040
        BIF_EDITBOX = 0x0010

        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None

        #Initial selection must not restrict the tree to that folder.
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND,
                                           wintypes.UINT, ctypes.c_void_p,
                                           ctypes.c_void_p)
        initial_buffer = ctypes.create_unicode_buffer(str(initial or ""))
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       ctypes.c_size_t, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        @callback_type
        def initialize_selection(hwnd, message, _value, _data):
            if message == 1 and initial:  #BFFM_INITIALIZED
                user32.SendMessageW(hwnd, 0x467, 1,
                                    ctypes.cast(initial_buffer, ctypes.c_void_p))
            return 0

        #260 会截断深度较长的中文目录，返回一个「看似存在」的残缺路径；放宽到 4096。
        display_name = ctypes.create_unicode_buffer(4096)
        info = BrowseInfo(
            hwndOwner=0,
            pidlRoot=0,
            pszDisplayName=ctypes.cast(display_name, ctypes.c_wchar_p),
            lpszTitle=title,
            ulFlags=BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX,
            lpfn=ctypes.cast(initialize_selection, ctypes.c_void_p),
            lParam=0,
            iImage=0,
        )
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return ""
        path_buffer = ctypes.create_unicode_buffer(4096)
        selected = ""
        if shell32.SHGetPathFromIDListW(pidl, path_buffer):
            selected = path_buffer.value
        ole32.CoTaskMemFree(pidl)
        return selected
    except Exception:
        return ""
