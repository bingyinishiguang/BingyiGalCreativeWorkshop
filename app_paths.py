"""区分源码态与冻结态的资源、数据和素材路径。"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

APP_DIR_FALLBACK = "BingyiGalCreativeWorkshop"
POINTER_NAME = "data-location.txt"
LINKS_NAME = "pack-links.json"

STARTUP_LOG_NAME = "startup.log"
SCAN_SUMMARY_NAME = "scan-summary.json"
SETTINGS_NAME = "settings.json"
PET_STATE_NAME = "pet-state.json"
LIBRARY_DIR_NAME = "Library"
SINGLE_EXPORT_DIR_NAME = "Single"
LIBRARY_DB_NAME = "library.sqlite3"
BATCH_DIR_NAME = "batch"
ISOLATION_DIR_NAME = "isolation"
DRAG_OUT_DIR_NAME = "DragOut"
ISOLATION_DECISIONS_NAME = "isolation-decisions.json"
BUNDLED_PACKS_DIR_NAME = "packs"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源根（ui/ 等）。冻结态为 sys._MEIPASS，开发态为项目目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """可写的“程序根”。冻结态为 exe 所在目录，开发态为项目目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def brand() -> dict:
    path = resource_root() / "ui" / "brand.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "appName": "冰翼Gal创作工坊",
            "appNameEn": "BingyiGalCreativeWorkshop",
            "tagline": "Galgame 素材工作台",
            "version": "0.0.0",
            "creator": "冰翼逆时光",
            "dataDirName": APP_DIR_FALLBACK,
        }


def app_name() -> str:
    return str(brand().get("appName") or "冰翼Gal创作工坊")


def default_data_dir() -> Path:
    if not is_frozen():
        return project_root() / "工作数据"
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    directory_name = str(brand().get("dataDirName") or APP_DIR_FALLBACK)
    current = base / directory_name

    legacy = base / "BingyiGalWorkshop"
    if directory_name == APP_DIR_FALLBACK and not current.exists() and legacy.is_dir():
        return legacy
    return current


def pointer_file() -> Path:
    return default_data_dir() / POINTER_NAME


def _dir_writable(path: Path) -> bool:
    """用唯一探测文件检查现有目录的写权限，不创建目标目录。"""
    try:
        if not path.is_dir():
            return False
        probe = path / f".write-probe-{os.getpid()}-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        try:
            probe.unlink()
        except OSError:

            pass
        return True
    except Exception:
        return False




_last_fallback_reason: str = ""


def last_fallback_reason() -> str:
    return _last_fallback_reason


def resolve_data_dir() -> Path:
    """冻结态优先使用指针文件记录的自选目录；任何异常都回退默认目录。"""
    global _last_fallback_reason
    _last_fallback_reason = ""
    default = default_data_dir()
    if not is_frozen():
        default.mkdir(parents=True, exist_ok=True)
        return default
    pointer = pointer_file()
    try:
        if pointer.exists():
            raw = pointer.read_text(encoding="utf-8").strip()

            target = Path(raw) if raw else None
            if target is None or not target.is_absolute():
                _last_fallback_reason = f"数据目录指针内容无效（{'空' if not raw else raw[:60]}），已回退默认目录"
            elif target.resolve() == default.resolve():
                _last_fallback_reason = ""
                return default
            elif _dir_writable(target):
                return target
            else:
                _last_fallback_reason = f"数据目录不可写或不存在：{target}"
    except Exception as error:
        _last_fallback_reason = f"读取数据目录指针失败：{error}"
    default.mkdir(parents=True, exist_ok=True)
    return default


def set_custom_data_dir(target: Path) -> None:
    """以临时文件和原子替换保存数据目录指针。"""
    pointer = pointer_file()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_name(f"{pointer.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(str(target), encoding="utf-8")
        os.replace(temporary, pointer)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def clear_custom_data_dir() -> None:
    try:
        pointer_file().unlink()
    except FileNotFoundError:
        pass


def packs_dir() -> Path:
    if is_frozen():
        return resolve_data_dir() / "sprite-packs"
    return project_root() / "sprite-packs"


def build_stamp() -> dict:
    """计算版本提醒状态；过期只提示，不禁用功能。"""
    info = brand()
    raw = str(info.get("betaDeadline") or "").strip()
    try:
        warn_days = int(info.get("betaWarnDays") or 7)
    except (TypeError, ValueError):
        warn_days = 7
    warn_days = max(0, min(warn_days, 365))
    message = str(info.get("betaMessage") or "").strip()
    result = {"configured": False, "deadline": "", "expired": False,
              "daysLeft": None, "warn": False, "warnDays": warn_days,
              "message": message}
    if not raw:
        return result
    try:
        deadline = date.fromisoformat(raw)
    except ValueError:

        return result
    days_left = (deadline - date.today()).days
    result.update({
        "configured": True,
        "deadline": deadline.isoformat(),
        "expired": days_left < 0,
        "daysLeft": days_left,
        "warn": 0 <= days_left <= warn_days,
    })
    return result


def process_age_seconds() -> float | None:
    """读取当前进程的实际存活时间；不支持时返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import time
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, os.getpid())
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time),
            )
            if not ok:
                return None

            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            created_at = ticks / 10_000_000 - 11_644_473_600
            return max(0.0, time.time() - created_at)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def bundled_packs_dir() -> Path:
    """返回安装目录下的 packs 路径；其中素材仅通过链接读取。"""
    return project_root() / BUNDLED_PACKS_DIR_NAME


def links_file(data_dir: Path) -> Path:
    return data_dir / LINKS_NAME
