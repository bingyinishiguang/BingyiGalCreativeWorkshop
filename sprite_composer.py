from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import OrderedDict
from typing import Iterable
from urllib.parse import parse_qs, quote, urlparse

from PIL import Image

import app_paths
import file_dialog
import pack_import
import scan_cache
from app_settings import AppSettings
from library_tags import build_auto_tags
from pbd_parser import PbdDocument, read_pbd
from sprite_library import SpriteLibrary
from production_api import ProductionAPI, POST_PATHS as PRODUCTION_POST_PATHS
from txt_parser import TxtBody, TxtCharacter, TxtLibrary, compose_txt, scan_txt_library


#记录启动阶段耗时，供本地诊断使用。
_BOOT_T0 = time.perf_counter()
_BOOT_LAST = [0.0]
_BOOT_MARKS: list[str] = []
#数据目录就绪前缓存日志，随后写入本地文件。
_BOOT_READY = False


def _boot_mark(stage: str) -> None:
    """记录一个启动阶段。数据目录未就绪时先攒着，就绪后直接写日志。"""
    elapsed = (time.perf_counter() - _BOOT_T0) * 1000
    delta = elapsed - _BOOT_LAST[0]
    _BOOT_LAST[0] = elapsed
    age = app_paths.process_age_seconds()
    age_text = f"进程创建后 {age * 1000:.0f} ms" if age is not None else "进程创建后 ? ms"
    line = f"[boot] {stage}：{age_text}（模块开始执行后 {elapsed:.0f} ms，距上一阶段 {delta:.0f} ms）"
    if _BOOT_READY:
        _startup_log(line)
    else:
        _BOOT_MARKS.append(line)


def _schedule_relaunch(delay_seconds: float = 0.8) -> bool:
    """延迟启动替代进程，以重新扫描后替换闭包持有的目录数据。"""
    def _relaunch() -> None:
        spawned = False
        try:
            import subprocess

            arguments = [sys.executable]
            if not app_paths.is_frozen():
                arguments.append(str(Path(__file__).resolve()))
            #保留启动参数，使重启继续使用原来的项目目录和界面模式。
            arguments.extend(sys.argv[1:])
            subprocess.Popen(arguments, cwd=str(Path(__file__).resolve().parent))
            spawned = True
        except Exception as error:
            _startup_log(f"重启失败（请手动重开程序）：{error!r}")
        if spawned:
            os._exit(0)

    try:
        threading.Timer(delay_seconds, _relaunch).start()
        return True
    except Exception:
        return False


def _machine_profile_lines() -> list[str]:
    """收集与启动性能相关的系统信息，写入本地诊断日志。"""
    lines: list[str] = []
    try:
        import platform

        lines.append(f"CPU 逻辑核心={os.cpu_count()}")
        lines.append(f"系统={platform.platform()}")
        lines.append(f"Python={platform.python_version()} 冻结态={app_paths.is_frozen()}")
    except Exception:
        pass
    #内存总量
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total_gb = status.ullTotalPhys / 1073741824
            avail_gb = status.ullAvailPhys / 1073741824
            lines.append(f"内存={total_gb:.1f} GB（可用 {avail_gb:.1f} GB）")
    except Exception:
        pass
    #系统 DPI 缩放
    try:
        import ctypes

        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi:
            lines.append(f"系统缩放={dpi / 96:.2f}")
    except Exception:
        pass
    #WebView2 运行时（主界面靠它渲染；缺失/过旧会明显拖慢或白屏）
    try:
        import winreg

        key = (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
               r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")
        for hive, path in ((winreg.HKEY_LOCAL_MACHINE, key),
                           (winreg.HKEY_CURRENT_USER, key.replace("WOW6432Node\\", ""))):
            try:
                with winreg.OpenKey(hive, path) as handle:
                    version, _ = winreg.QueryValueEx(handle, "pv")
                    lines.append(f"WebView2 运行时={version}")
                    break
            except OSError:
                continue
        else:
            lines.append("WebView2 运行时=未检测到（主键缺失，可能需要安装运行时）")
    except Exception:
        pass
    #数据盘剩余空间（素材包会占几百 MB 到几 GB）
    try:
        import shutil

        usage = shutil.disk_usage(str(app_paths.resolve_data_dir()))
        lines.append(f"数据盘剩余={usage.free / 1073741824:.1f} GB")
    except Exception:
        pass
    return lines


def _flush_boot_marks() -> None:
    """数据目录就绪：把攒下的打点写进日志，并打开"之后直接落盘"的开关。"""
    global _BOOT_READY
    _BOOT_READY = True
    for line in _BOOT_MARKS:
        _startup_log(line)
    _BOOT_MARKS.clear()


_boot_mark("模块导入完成")


CANVAS_SIZE = (1280, 1280)
POSITION_RE = re.compile(r"pos,(-?\d+),(-?\d+),(\d+),(\d+)")
BODY_GROUP_RE = re.compile(r"_no([a-z])", re.IGNORECASE)
FACE_GROUP_RE = re.compile(r"^([a-z])(\d{4})[a-z]*$", re.IGNORECASE)
PNG_FACE_ACCESSORY_CODES = frozenset(("0097", "0098", "0099"))
TXT_COMMON_FACE_IDS = ("01", "02", "03", "21", "22")
TXT_UNSAFE_OUTFIT_RE = re.compile(r"裸|水着|泳|ビキニ|下着|内衣|風呂|シャワー|タオル", re.IGNORECASE)
ISOLATED_BODY_RE = re.compile(r"裸")
SWIMWEAR_BODY_RE = re.compile(r"水着|泳装|泳衣|ビキニ|スク水|水泳|プール", re.IGNORECASE)
SLEEPWEAR_BODY_RE = re.compile(r"パジャマ|寝間着|寝巻|ネグリジェ|睡衣|ナイトウェア", re.IGNORECASE)
PNG_EXPOSED_CODES = ("0000", "0010")
REMOVED_BODY_CODES = {
    "华乃": frozenset(("0900", "0910")),
    "天梨": frozenset(("0900",)),
    "妃爱": frozenset(("0900", "0910")),
    "小天使": frozenset(("0001", "0011", "0900", "0910")),
    "诗樱": frozenset(("0001", "0010", "0011", "0900", "0910")),
}
REMOVED_BODY_RE = re.compile(r"_no[a-z](\d{4})(?:\D|$)", re.IGNORECASE)


def removed_body(character: str, body: str) -> bool:
    match = REMOVED_BODY_RE.search(body)
    return bool(match and match.group(1) in REMOVED_BODY_CODES.get(character, ()))


TOKEN_COOKIE = "bgw-token"
_ABS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s'\"）)，。;；]*")
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)
#串行写入图库，合成并发由独立信号量限制。
_LIBRARY_WRITE_LOCK = threading.Lock()

_COMPOSE_SLOTS = threading.BoundedSemaphore(2)

#许可文件只接受白名单名称；Windows 使用 LICENSE.txt 副本。
_OPENABLE_PROJECT_FILES = frozenset({
    "LICENSE",
    "LICENSE.txt",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "NOTICE",
})
#缓存编码后的表情预览字节，避免重复解码高分辨率图层。
_PREVIEW_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_PREVIEW_CACHE_LOCK = threading.Lock()
_PREVIEW_CACHE_MAX = 96


def _diagnostics(data_dir: Path, output_root: Path, characters: dict, lime_characters: dict,
                 txt_library: TxtLibrary, library: SpriteLibrary, settings: AppSettings,
                 catalog: dict) -> dict:
    """汇总素材、图库、输出目录与运行依赖的可用状态。"""
    checks: list[dict] = []

    def add(item_id: str, label: str, ok: bool, detail: str, hint: str = "") -> None:
        checks.append({"id": item_id, "label": label, "ok": bool(ok), "detail": detail, "hint": hint})

    #版本与素材包形态
    brand = app_paths.brand()
    packs = [name for name, _path, _source in pack_import.iter_pack_roots(
        app_paths.packs_dir(), app_paths.links_file(data_dir))]
    if not packs:
        variant = "空版（未导入任何素材包）"
    else:
        joined = "、".join(packs)
        if any("精简" in name for name in packs):
            variant = f"精简版（{joined}）"
        elif any("全量" in name or "离线" in name for name in packs):
            variant = f"全量离线版（{joined}）"
        else:
            variant = f"自定义素材包（{joined}）"
    add("version", "程序版本 / 素材包形态",
        True, f"v{brand.get('version', '?')} · {variant}")

    #数据目录可写（写不进去 = 立绘库、设置、导出全废）
    probe = data_dir / ".write-probe"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add("dataDir", "数据目录可写", True, str(data_dir))
    except Exception as error:
        add("dataDir", "数据目录可写", False, f"{data_dir}（{_redact_paths(error)}）",
            "换一个可写位置，或检查杀软是否拦截了写入")

    #素材扫描结果
    games = len(catalog)
    roles = sum(len(entry.get("characters", {})) for entry in catalog.values())
    add("catalog", "素材扫描", bool(games and roles),
        f"{games} 部作品 / {roles} 个可合成角色",
        "到设置页「素材包导入」导入素材包目录或 zip" if not (games and roles) else "")

    #三个适配器各自能不能用
    for label, count, adapter in (
        ("PNG 内嵌坐标", len(characters), "png-position-v1"),
        ("PBD 配方", len(lime_characters), "krkr-pbd-v1"),
        ("TXT 坐标", sum(len(game) for game in txt_library.values()), "krkr-txt-v1"),
    ):
        add(f"adapter:{adapter}", f"适配器 {label}", count > 0,
            f"{count} 个角色" if count else "当前素材包里没有这种格式",
            "" if count else "缺少这种格式不影响其他格式使用")

    #立绘库索引
    try:
        listed = library.list(False)
        add("library", "立绘库索引可读", True, f"{listed.get('total', 0)} 张普通立绘")
    except Exception as error:
        add("library", "立绘库索引可读", False, _redact_paths(error),
            "立绘库数据库可能损坏或被占用，可尝试重启程序")

    #取用精灵组件（缺 PySide6 会退回旧兼容窗）
    try:
        import importlib.util
        has_pyside = importlib.util.find_spec("PySide6") is not None
    except Exception:
        has_pyside = False
    add("companion", "冰翼取用精灵组件", has_pyside,
        "可用" if has_pyside else "缺少组件，会退回旧的兼容取用窗",
        "" if has_pyside else "安装完整版即可使用新精灵界面")

    #拖放模块（拖进剪映的能力）
    try:
        import windows_file_drag  #noqa: F401
        add("drag", "拖进剪映（原生拖放）", True, "可用")
    except Exception as error:
        add("drag", "拖进剪映（原生拖放）", False, _redact_paths(error),
            "缺少拖放组件，将无法把立绘拖进剪映")

    if getattr(settings, "was_reset", False):
        add("settings", "设置文件", False, "上次读取时发现损坏，已备份并回退默认值",
            "设置目录里能看到 设置.json.broken-* 备份，可交给开发者排查")
    else:
        add("settings", "设置文件", True, "正常")

    problems = [item for item in checks if not item["ok"]]
    #「某格式没有素材」不算故障，避免空版被报一堆红
    hard = [item for item in problems if not item["id"].startswith("adapter:")]
    return {
        "version": str(brand.get("version", "")),
        "variant": variant,
        "dataDir": str(data_dir),
        "settingsReset": bool(getattr(settings, "was_reset", False)),
        "checks": checks,
        "problems": len(problems),
        "hardProblems": len(hard),
        #设置页「日志与诊断包」子页面要显示日志位置，一键打开所在目录。
        "logPath": str(data_dir / app_paths.STARTUP_LOG_NAME),
        "summary": ("一切正常，可以正常使用" if not hard
                    else f"发现 {len(hard)} 项需要处理，详见下面清单"),
    }


def _real_path(raw: Path) -> Path:
    """统一真实路径，处理 Windows 扩展前缀与本机 UNC 管理共享。"""
    text = str(raw).strip().strip('"').strip()
    if text.startswith("\\\\?\\") or text.startswith("\\\\.\\"):
        text = text[4:]
    #UNC 管理共享：\\localhost\C$\... / \\127.0.0.1\C$\... → C:\...
    match = re.match(r"^\\\\[^\\]+\\([A-Za-z])\$[\\/]?(.*)$", text)
    if match:
        drive, rest = match.group(1), match.group(2)
        text = f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    path = Path(text).expanduser().resolve()
    #realpath 会把 8.3 短名、映射盘符、符号链接归一到真实位置。
    try:
        path = Path(os.path.realpath(path))
    except OSError:
        pass
    return path


def _reject_dangerous_source(raw: str, code_dir: Path) -> str:
    """拒绝系统、程序及整盘目录，避免错误复制导入。"""
    if not raw:
        return "请选择素材包目录"
    try:
        source = _real_path(Path(raw))
    except Exception:
        return "目录路径无法解析"
    if not source.is_dir():
        return "目录不存在或不是文件夹"
    if source.parent == source:  #盘根，例如 D:\
        return "不能直接导入整个磁盘根目录"
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    for blocked in (Path(windows), Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                    Path(os.environ.get("USERPROFILE", "")) / "Desktop"):
        try:
            if not blocked.exists():
                continue
            blocked_real = _real_path(blocked)
            if source == blocked_real or source.is_relative_to(blocked_real):
                return f"出于安全考虑，不能导入系统或程序目录：{blocked.name}"
        except Exception:
            continue
    try:
        code_real = _real_path(code_dir)
        if source == code_real or source.is_relative_to(code_real):
            return "不能把程序自身目录当作素材包导入"
    except Exception:
        pass
    return ""


def register_bundled_packs(data_dir: Path) -> list[str]:
    """以链接登记安装目录中的素材包，避免复制到个人数据目录。"""
    bundled = app_paths.bundled_packs_dir()
    if not bundled.is_dir():
        return []
    links_path = app_paths.links_file(data_dir)
    #清单读不出来（被手改坏/云同步截断/被杀毒锁住）时跳过内置包登记，
    #不要在这里抛异常把启动流程打断（这是启动路径）。
    try:
        existing = {str(Path(item["path"])) for item in pack_import.load_links(links_path)}
    except ValueError as error:
        _startup_log(f"链接素材包清单无法读取，已跳过内置包自动登记：{error}")
        return []
    registered: list[str] = []
    for child in sorted(bundled.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        #只有真的含素材（games 下能找到 .pbd/.txt）才登记，避免登记一个空目录
        if not any(child.rglob("*.pbd")) and not any(child.rglob("*.txt")):
            continue
        if str(child.resolve()) in existing:
            continue
        pack_import.add_link(links_path, child.resolve())
        registered.append(child.name)
    if registered:
        _startup_log(f"已自动登记安装包内置素材包：{'、'.join(registered)}")
    return registered


def _redact_paths(text: object) -> str:
    """隐藏响应错误信息中的本机绝对路径。"""
    return _ABS_PATH_RE.sub("<本机路径>", str(text))


def _token_ok(handler, token: str) -> bool:
    """校验会话 cookie 与 Origin，防止外部网页调用本机写入接口。"""
    if not token:
        return True
    header = handler.headers.get("X-Auth-Token")
    if header and secrets.compare_digest(header, token):
        return True
    for part in (handler.headers.get("Cookie") or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == TOKEN_COOKIE and secrets.compare_digest(value, token):
            return True
    return False


def _append_log_line(tag: str, message: str) -> None:
    """加锁追加日志；写入失败不影响请求处理。"""
    try:
        path = app_paths.resolve_data_dir() / app_paths.STARTUP_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{tag} {datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n"
        with _LOG_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        pass


_LOG_LOCK = threading.Lock()


def _startup_log(message: str) -> None:
    """把启动期诊断信息追加写入数据目录/startup.log（失败静默）。"""
    _append_log_line("startup", message)


#请求日志单独打标，方便设置页「导出诊断包」按级别抽取（）。
def _request_log(message: str) -> None:
    _append_log_line("request", message)


_LOG_MAX_BYTES = 1_500_000
_LOG_KEEP_LINES = 4000


def _trim_startup_log() -> int:
    """日志超过上限时只保留尾部，返回裁掉的行数（0 = 没裁）。"""
    try:
        path = app_paths.resolve_data_dir() / app_paths.STARTUP_LOG_NAME
        if not path.is_file() or path.stat().st_size <= _LOG_MAX_BYTES:
            return 0
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) <= _LOG_KEEP_LINES:
            return 0
        removed = len(lines) - _LOG_KEEP_LINES
        kept = lines[-_LOG_KEEP_LINES:]
        kept.insert(0, f"[startup {datetime.now():%Y-%m-%d %H:%M:%S}] 日志超过上限，已裁掉最早 {removed} 行")
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return removed
    except Exception:
        return 0


def build_diagnostics_archive(data_dir: Path, output_root: Path, settings, catalog: dict,
                              library: SpriteLibrary) -> Path:
    """打包日志、设置摘要和目录统计，并脱敏个人路径。"""
    import zipfile

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    destination = output_root / f"diagnostics-{stamp}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    def safe_text(reader) -> str:
        try:
            return reader()
        except Exception as error:  #pragma: no cover - 采集失败不该阻断导出
            return f"(采集失败：{error})"

    entries: dict[str, str] = {}
    log_path = data_dir / app_paths.STARTUP_LOG_NAME
    entries["startup.log"] = safe_text(
        lambda: log_path.read_text(encoding="utf-8", errors="replace")[-400_000:])
    summary_path = data_dir / app_paths.SCAN_SUMMARY_NAME
    entries["scan-summary.json"] = safe_text(
        lambda: summary_path.read_text(encoding="utf-8", errors="replace"))
    settings_path = data_dir / app_paths.SETTINGS_NAME
    entries["settings.json"] = safe_text(
        lambda: settings_path.read_text(encoding="utf-8", errors="replace"))
    #版本信息放最前面：收到诊断包时第一眼就要能看出"他用的是哪个包"
    brand_info = app_paths.brand()
    beta = app_paths.build_stamp()
    version_line = f"版本={brand_info.get('version')}"
    label = str(brand_info.get("versionLabel") or "").strip()
    if label:
        version_line += f" {label}"
    beta_line = "内测期限=未配置"
    if beta["configured"]:
        beta_line = (f"内测期限={beta['deadline']}"
                     f"（{'已过期' if beta['expired'] else '剩余 ' + str(beta['daysLeft']) + ' 天'}）")
    entries["environment.txt"] = "\n".join([
        version_line,
        beta_line,
        *[f"{line}" for line in _machine_profile_lines()],
        f"冻结态={app_paths.is_frozen()}",
        f"程序目录={app_paths.project_root()}",
        f"资源目录={app_paths.resource_root()}",
        f"数据目录={data_dir}",
        f"素材目录={app_paths.packs_dir()}",
    ]) + "\n"
    entries["catalog.json"] = json.dumps({
        "works": len(catalog),
        "characters": sum(len(entry.get("characters", {})) for entry in catalog.values()),
        "games": sorted(catalog.keys()),
    }, ensure_ascii=False, indent=2) + "\n"
    entries["library.json"] = safe_text(lambda: json.dumps({
        "total": library.list(False)["total"],
        "trash": library.list(False, trash=True)["total"],
        "special": library.list(True)["total"],
        "root": str(library.root),
    }, ensure_ascii=False, indent=2) + "\n")
    try:
        entries["diagnostics.json"] = json.dumps(
            _diagnostics(data_dir, output_root, {}, {}, {}, library, settings, catalog),
            ensure_ascii=False, indent=2) + "\n"
    except Exception as error:
        entries["diagnostics.json"] = json.dumps({"error": str(error)}, ensure_ascii=False) + "\n"

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return destination


def _count_scan_media(root: Path) -> tuple[int, int, int]:
    """统计扫描根目录下的 .pbd / .txt / 总文件数（用于启动诊断，不修改任何素材）。"""
    pbd = txt = files = 0
    if not root.is_dir():
        return 0, 0, 0
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        files += 1
        suffix = item.suffix.lower()
        if suffix == ".pbd":
            pbd += 1
        elif suffix == ".txt":
            txt += 1
    return pbd, txt, files


def _process_rss_mb() -> float:
    """返回当前进程工作集大小（MB）；仅 Windows 精确，其余平台回退 0。"""
    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = (
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            )

        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def _write_scan_summary(payload: dict) -> None:
    """把扫描摘要写入数据目录/scan-summary.json，供设置页展示最近一次扫描结果。"""
    try:
        path = app_paths.resolve_data_dir() / app_paths.SCAN_SUMMARY_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


@dataclass(frozen=True)
class IsolationPolicy:
    allowed: frozenset[tuple[str, str, str]] = frozenset()
    excluded: frozenset[tuple[str, str, str]] = frozenset()

    @classmethod
    def load(cls, path: Path) -> IsolationPolicy:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError(f"隔离审核决定版本不受支持：{path}")

        def entries(key: str) -> frozenset[tuple[str, str, str]]:
            values = data.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f"隔离审核决定的 {key} 必须是列表：{path}")
            result = []
            for item in values:
                if not isinstance(item, dict) or not all(isinstance(item.get(field), str) for field in ("game", "character", "body")):
                    raise ValueError(f"隔离审核决定的 {key} 条目缺少作品、角色或完整组合名：{path}")
                result.append((item["game"], item["character"], item["body"]))
            return frozenset(result)

        allowed = entries("allow")
        excluded = entries("exclude")
        if allowed & excluded:
            raise ValueError(f"同一组合同时出现在放行与隔离名单：{path}")
        return cls(allowed, excluded)

    def category(self, game: str, character: str, body: str) -> str:
        key = game, character, body
        if removed_body(character, body):
            return "exposed"
        if key in self.excluded:
            return "exposed"
        if key in self.allowed:
            return "normal"
        if ISOLATED_BODY_RE.search(body) or (game == "常轨脱离" and body.endswith(PNG_EXPOSED_CODES)):
            return "exposed"
        if SWIMWEAR_BODY_RE.search(body):
            return "swimwear"
        if SLEEPWEAR_BODY_RE.search(body):
            return "sleepwear"
        return "normal"

    def is_isolated(self, game: str, character: str, body: str) -> bool:
        return self.category(game, character, body) == "exposed"


@dataclass(frozen=True)
class Layer:
    path: Path
    x: int
    y: int
    width: int
    height: int
    group: str

    @property
    def name(self) -> str:
        return self.path.stem


@dataclass
class Character:
    name: str
    bodies: list[Layer]
    faces: list[Layer]


@dataclass
class LimePose:
    character: str
    name: str
    pbd_path: Path
    document: PbdDocument
    dresses: dict[str, list[str]]
    faces: dict[str, list[str]]

    @property
    def label(self) -> str:
        return self.pbd_path.stem


def png_position(path: Path) -> tuple[int, int, int, int]:
    with Image.open(path) as image:
        comment = image.info.get("comment", "")
        if isinstance(comment, bytes):
            comment = comment.decode("utf-8", errors="replace")
    match = POSITION_RE.search(str(comment))
    if not match:
        raise ValueError(f"PNG 没有 pos 坐标元数据：{path}")
    return tuple(int(value) for value in match.groups())


def layer_from_path(path: Path, kind: str) -> Layer | None:
    stem = path.stem
    match = BODY_GROUP_RE.search(stem) if kind == "body" else FACE_GROUP_RE.match(stem)
    if not match or (kind == "face" and match.group(2) in PNG_FACE_ACCESSORY_CODES):
        return None
    x, y, width, height = png_position(path)
    return Layer(path, x, y, width, height, match.group(1).lower())


def scan_characters(source_root: Path, warnings: list[str] | None = None) -> dict[str, Character]:
    characters: dict[str, Character] = {}
    issues = warnings if warnings is not None else []
    if not source_root.is_dir():
        return characters
    for character_dir in sorted((item for item in source_root.iterdir() if item.is_dir()), key=lambda p: p.name):
        bodies: list[Layer] = []
        faces: list[Layer] = []
        for path in sorted(character_dir.rglob("*.png"), key=lambda p: p.name):
            if BODY_GROUP_RE.search(path.stem):
                if removed_body(character_dir.name, path.stem):
                    continue
                kind = "body"
            elif (face_match := FACE_GROUP_RE.match(path.stem)) and face_match.group(2) not in PNG_FACE_ACCESSORY_CODES:
                kind = "face"
            else:
                continue
            try:
                layer = layer_from_path(path, kind)
            except Exception as error:
                #单个坏图/缺 pos 元数据不能让整个启动失败：跳过并记录，稍后汇总给用户。
                issues.append(f"{character_dir.name}/{path.name}: {error}")
                continue
            if layer is None:
                continue
            (bodies if kind == "body" else faces).append(layer)
        if bodies and faces:
            characters[character_dir.name] = Character(character_dir.name, bodies, faces)
    return characters


def scan_lime_poses(source_root: Path, warnings: list[str] | None = None) -> dict[str, list[LimePose]]:
    characters: dict[str, list[LimePose]] = {}
    issues = warnings if warnings is not None else []
    if not source_root.is_dir():
        return characters
    for character_dir in sorted((item for item in source_root.iterdir() if item.is_dir()), key=lambda p: p.name):
        poses: list[LimePose] = []
        for pbd_path in sorted(character_dir.glob("*.pbd"), key=lambda p: p.name):
            sinfo_path = pbd_path.with_suffix(".sinfo")
            if not sinfo_path.exists():
                continue
            try:
                lines = sinfo_path.read_text(encoding="utf-16").splitlines()
            except (UnicodeError, OSError) as error:
                #现在只跳过这一个姿势，把原因记进扫描警告。
                issues.append(f"{character_dir.name}/{sinfo_path.name}: 配方读取失败（需要 UTF-16 编码）：{error}")
                continue
            dresses: dict[str, list[str]] = {}
            faces: dict[str, list[str]] = {}
            for line in lines:
                fields = line.split("\t")
                if len(fields) >= 5 and fields[0] == "dress":
                    key = f"{fields[1]}｜动作{fields[3]}"
                    dresses.setdefault(key, []).append(fields[4])
                elif len(fields) >= 4 and fields[0] == "face":
                    faces.setdefault(fields[1], []).append(fields[3])
            if not (dresses and faces):
                continue
            try:
                document = read_pbd(pbd_path)
            except Exception as error:
                issues.append(f"{character_dir.name}/{pbd_path.name}: PBD 读取失败：{error}")
                continue
            poses.append(LimePose(character_dir.name, pbd_path.stem, pbd_path, document, dresses, faces))
        if poses:
            characters[character_dir.name] = poses
    return characters


def compose(body: Layer, face: Layer, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    if body.group != face.group:
        raise ValueError(f"姿势组不匹配：{body.name} / {face.name}")
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    with Image.open(body.path) as image:
        canvas.alpha_composite(image.convert("RGBA"), (body.x, body.y))
    with Image.open(face.path) as image:
        canvas.alpha_composite(image.convert("RGBA"), (face.x, face.y))
    return canvas


def compose_lime(pose: LimePose, dress_key: str, face_key: str) -> Image.Image:
    document = pose.document
    canvas = Image.new("RGBA", (document.width, document.height), (0, 0, 0, 0))
    by_name = {layer.name: layer for layer in document.layers}
    names = pose.dresses[dress_key] + pose.faces[face_key]
    for recipe_name in names:
        normalized = recipe_name.replace("\\", "/")
        layer = by_name.get(normalized)
        if not layer:
            canonical = lambda value: value.replace("\\", "").replace("/", "").replace("_", "")
            recipe_canonical = canonical(normalized)
            suffix_matches = [candidate for candidate in document.layers if recipe_canonical.endswith(canonical(candidate.name))]
            layer = max(suffix_matches, key=lambda candidate: len(candidate.name), default=None)
        if not layer:
            raise ValueError(f"{pose.label} 找不到配方图层：{recipe_name}")
        image_path = pose.pbd_path.parent / layer.filename
        with Image.open(image_path) as source:
            image = source.convert("RGBA")
        if layer.opacity < 255:
            alpha = image.getchannel("A").point(lambda value: value * layer.opacity // 255)
            image.putalpha(alpha)
        canvas.alpha_composite(image, (layer.left, layer.top))
    return canvas


def trim_transparent(image: Image.Image, padding: int = 4) -> Image.Image:
    """Crop empty alpha space while retaining a small safety margin."""
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return rgba
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(rgba.width, bbox[2] + padding)
    bottom = min(rgba.height, bbox[3] + padding)
    cropped = rgba.crop((left, top, right, bottom))
    cropped.info["bingyi_geometry"] = json.dumps(dict(width=rgba.width,height=rgba.height,left=left,top=top))
    return cropped


def faces_for_body(character: Character, body: Layer) -> list[Layer]:
    return [face for face in character.faces if face.group == body.group]


#按所需文件存在性过滤组合，不仅依赖完整元数据。


def _directory_files(directory: Path, cache: dict[Path, set[str]]) -> set[str]:
    """列出一个目录下的文件名（带缓存，避免同一姿势反复读盘）。"""
    folder = directory
    cached = cache.get(folder)
    if cached is not None:
        return cached
    try:
        names = {entry.name for entry in folder.iterdir() if entry.is_file()}
    except OSError:
        names = set()
    cache[folder] = names
    return names


def _lime_pose_files(pose: LimePose, cache: dict[Path, set[str]]) -> set[str]:
    return _directory_files(pose.pbd_path.parent, cache)


def _canonical_layer_key(value: str) -> str:
    return value.replace("\\", "").replace("/", "").replace("_", "")


def _lime_layer_filename(pose: LimePose, recipe_name: str,
                         cache: dict[tuple[int, str], str | None] | None = None) -> str | None:
    """缓存配方名到 PNG 文件名的映射，与合成路径使用同一规则。"""
    store = cache if cache is not None else {}
    key = (id(pose), recipe_name)
    if key in store:
        return store[key]
    normalized = recipe_name.replace("\\", "/")
    by_name = {layer.name: layer for layer in pose.document.layers}
    layer = by_name.get(normalized)
    if layer is None:
        recipe_canonical = _canonical_layer_key(normalized)
        matches = [candidate for candidate in pose.document.layers
                   if recipe_canonical.endswith(_canonical_layer_key(candidate.name))]
        layer = max(matches, key=lambda candidate: len(candidate.name), default=None)
    result = layer.filename if layer is not None else None
    store[key] = result
    return result


def _lime_combination_available(pose: LimePose, dress_key: str, face_key: str,
                                cache: dict[Path, set[str]],
                                layer_names: dict[tuple[int, str], str | None] | None = None) -> bool:
    """检查服装和表情所需的每个图层均能解析且图片存在。"""
    available = _lime_pose_files(pose, cache)
    if not available:  #目录都读不到时保守放行，避免把能用的组合误删
        return True
    for recipe_name in [*pose.dresses.get(dress_key, ()), *pose.faces.get(face_key, ())]:
        filename = _lime_layer_filename(pose, recipe_name, layer_names)
        if filename is None or filename not in available:
            return False
    return True


def filter_lime_catalog(poses: list[LimePose], faces: dict[str, list[str]],
                        cache: dict[Path, set[str]] | None = None,
                        layer_cache: dict[tuple[int, str], str | None] | None = None) -> dict[str, list[str]]:
    """按文件存在性过滤 PBD 姿态的「服装 → 表情」表。"""
    store = cache if cache is not None else {}
    layers = layer_cache if layer_cache is not None else {}
    result: dict[str, list[str]] = {}
    for pose in poses:
        for dress_key in pose.dresses:
            body_label = f"{pose.label}｜{dress_key}"
            if body_label in faces:
                keep = [face for face in faces[body_label]
                        if _lime_combination_available(pose, dress_key, face, store, layers)]
                if keep:
                    result[body_label] = keep
    return result


def _exists(path: Path, cache: dict[Path, bool]) -> bool:
    """缓存当前目录扫描期间的文件存在性，避免重复访问磁盘。"""
    known = cache.get(path)
    if known is None:
        known = path.is_file()
        cache[path] = known
    return known


def filter_png_catalog(characters: dict[str, Character],
                       cache: dict[Path, bool] | None = None) -> dict[str, dict[str, list[str]]]:
    """按文件存在性过滤 PNG 适配器的「服装 → 表情」表。"""
    store = cache if cache is not None else {}
    result: dict[str, dict[str, list[str]]] = {}
    for name, character in characters.items():
        bodies: dict[str, list[str]] = {}
        for body in character.bodies:
            faces = [face for face in faces_for_body(character, body) if _exists(face.path, store)]
            if faces and _exists(body.path, store):
                bodies[body.name] = [face.name for face in faces]
        if bodies:
            result[name] = bodies
    return result


def filter_txt_catalog(txt_library: TxtLibrary,
                       cache: dict[Path, bool] | None = None) -> dict[str, dict[str, dict[str, list[str]]]]:
    """仅保留服装与表情配方所需文件完整的 TXT 组合。"""
    store = cache if cache is not None else {}
    layer_cache: dict[int, dict[str, bool]] = {}
    result: dict[str, dict[str, dict[str, list[str]]]] = {}
    for game_name, characters in txt_library.items():
        game: dict[str, dict[str, list[str]]] = {}
        for name, character in characters.items():
            bodies: dict[str, list[str]] = {}
            for body_label, spec in character.bodies.items():
                pose = spec.pose
                if not _txt_layer_files_exist(pose, pose.dresses.get(spec.dress_name, ()), store, layer_cache):
                    continue
                faces = [face for face in ordered_txt_faces(spec)
                         if _txt_layer_files_exist(pose, pose.faces.get(face, ()), store, layer_cache)]
                if faces:
                    bodies[body_label] = faces
            if bodies:
                game[name] = bodies
        if game:
            result[game_name] = game
    return result


def _txt_layer_files_exist(pose: TxtPose, keys: Iterable[str], store: dict[Path, bool],
                           layer_cache: dict[int, dict[str, bool]]) -> bool:
    """配方里这组层代码对应的图片文件是否都在（结果按姿势缓存）。"""
    per_pose = layer_cache.get(id(pose))
    if per_pose is None:
        per_pose = {}
        layer_cache[id(pose)] = per_pose
    for key in keys:
        known = per_pose.get(key)
        if known is None:
            layer = pose.layers.get(key)
            known = bool(layer is not None and _exists(layer.image_path, store))
            per_pose[key] = known
        if not known:
            return False
    return True


def txt_body_priority(label: str) -> tuple[int, int, str]:
    unsafe = 100 if TXT_UNSAFE_OUTFIT_RE.search(label) else 0
    preference = 20
    for index, token in enumerate(("制服", "私服", "通常", "メイド", "女仆", "和服", "着物")):
        if token in label:
            preference = index
            break
    action_penalty = 0 if "动作1" in label else 1
    return unsafe + preference, action_penalty, label.casefold()


def ordered_txt_faces(body: TxtBody) -> list[str]:
    faces = list(body.pose.faces)
    result = [face for face in TXT_COMMON_FACE_IDS if face in body.pose.faces]
    for pattern in (r"通常|基本|ベース|真顔", r"微笑|笑顔|喜笑", r"驚|きょとん", r"困|思案", r"怒|不満"):
        match = next((face for face in faces if face not in result and re.search(pattern, face, re.IGNORECASE)), None)
        if match:
            result.append(match)
    result.extend(face for face in faces if face not in result)
    return result


def safe_filename(text: str, max_length: int = 160) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", text).strip().rstrip(".")
    #Windows 保留设备名不能当文件名（CON/PRN/AUX/NUL/COM1-9/LPT1-9），
    #带扩展名也不行（CON.png 同样打不开），所以按主干名判断并加前缀。
    if cleaned and cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    return (cleaned[:max_length].rstrip(". ") or "未命名")


def catalog_character(game_name: str, character_name: str, bodies: dict[str, list[str]], policy: IsolationPolicy) -> dict:
    categories = {body: policy.category(game_name, character_name, body) for body in bodies}
    return {
        "bodies": bodies,
        "bodyCategories": categories,
        "isolatedBodies": [body for body, category in categories.items() if category == "exposed"],
    }


def web_catalog(characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary, policy: IsolationPolicy | None = None, existing_only: bool = False) -> dict:
    """生成作品、角色与组合清单；existing_only 时过滤缺失图片。"""
    policy = policy or IsolationPolicy()
    result: dict[str, dict] = {}
    #一次 catalog 构建共用一份"文件在不在"的缓存（见 _exists 的说明）。
    exists_cache: dict[Path, bool] = {}
    if characters:
        available = filter_png_catalog(characters, exists_cache) if existing_only else None
        game = {"characters": {}}
        for name, character in characters.items():
            if existing_only:
                if name not in (available or {}):
                    continue
                bodies = dict((available or {})[name])
            else:
                bodies = {body.name: [face.name for face in faces_for_body(character, body)] for body in character.bodies}
            game["characters"][name] = catalog_character("常轨脱离", name, bodies, policy)
        result["常轨脱离"] = game
    if lime_characters:
        cache: dict[Path, set[str]] = {}
        layer_cache: dict[tuple[int, str], str | None] = {}
        game = {"characters": {}}
        for name, poses in lime_characters.items():
            bodies: dict[str, list[str]] = {}
            for pose in poses:
                for dress in pose.dresses:
                    bodies[f"{pose.label}｜{dress}"] = list(pose.faces)
            if existing_only:
                bodies = filter_lime_catalog(poses, bodies, cache, layer_cache)
                if not bodies:
                    continue
            game["characters"][name] = catalog_character("LimeLightLemonadeJam", name, bodies, policy)
        result["LimeLightLemonadeJam"] = game
    txt_available = filter_txt_catalog(txt_library, exists_cache) if existing_only else None
    for game_name, txt_characters in txt_library.items():
        game = {"characters": {}}
        for name, character in txt_characters.items():
            if existing_only:
                bodies = dict((txt_available or {}).get(game_name, {}).get(name, {}))
                if not bodies:
                    continue
            else:
                ordered_bodies = sorted(character.bodies, key=txt_body_priority)
                bodies = {
                    body_label: ordered_txt_faces(character.bodies[body_label])
                    for body_label in ordered_bodies
                }
            game["characters"][name] = catalog_character(game_name, name, bodies, policy)
        result[game_name] = game
    return result


def write_isolation_report(catalog: dict, destination: Path, policy: IsolationPolicy) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("作品", "角色", "完整组合名", "状态", "依据"))
        writer.writeheader()
        for game_name, game in catalog.items():
            for character_name, character in game["characters"].items():
                for body_name in character["isolatedBodies"]:
                    reviewed = (game_name, character_name, body_name) in policy.excluded
                    writer.writerow({
                        "作品": game_name,
                        "角色": character_name,
                        "完整组合名": body_name,
                        "状态": "人工确认隔离" if reviewed else "待人工审核",
                        "依据": "人工决定" if reviewed else ("名称含裸" if ISOLATED_BODY_RE.search(body_name) else "常轨编号 0000／0010"),
                    })
                    count += 1
    return count


def web_composite_raw(game: str, character_name: str, body_name: str, face_name: str, characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary) -> Image.Image:
    if game == "常轨脱离":
        character = characters[character_name]
        body = next(item for item in character.bodies if item.name == body_name)
        face = next(item for item in character.faces if item.name == face_name and item.group == body.group)
        return compose(body, face)
    if game == "LimeLightLemonadeJam":
        poses = lime_characters[character_name]
        pose = next(item for item in poses if body_name.startswith(item.label + "｜"))
        dress = body_name[len(pose.label) + 1:]
        return compose_lime(pose, dress, face_name)
    body = txt_library[game][character_name].bodies[body_name]
    return compose_txt(body, face_name)


def web_composite(game: str, character_name: str, body_name: str, face_name: str, characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary) -> Image.Image:
    return trim_transparent(web_composite_raw(game, character_name, body_name, face_name, characters, lime_characters, txt_library))


def layer_visible_box(path: Path, left: int, top: int) -> tuple[int, int, int, int] | None:
    with Image.open(path) as image:
        bounds = image.getchannel("A").getbbox() if "A" in image.getbands() else image.convert("RGBA").getchannel("A").getbbox()
    if bounds is None:
        return None
    return left + bounds[0], top + bounds[1], left + bounds[2], top + bounds[3]


def expression_layer_boxes(game: str, character_name: str, body_name: str, face_name: str,
                           characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary) -> list[tuple[int, int, int, int]]:
    if game == "常轨脱离":
        character = characters[character_name]
        face = next(item for item in character.faces if item.name == face_name)
        candidates = [(face.path, face.x, face.y)]
    elif game == "LimeLightLemonadeJam":
        pose = next(item for item in lime_characters[character_name] if body_name.startswith(item.label + "｜"))
        candidates = []
        for recipe_name in pose.faces[face_name]:
            normalized = recipe_name.replace("\\", "/")
            layer = next((item for item in pose.document.layers if item.name == normalized), None)
            if layer is None:
                canonical = lambda value: value.replace("\\", "").replace("/", "").replace("_", "")
                layer = max((item for item in pose.document.layers if canonical(normalized).endswith(canonical(item.name))),
                            key=lambda item: len(item.name), default=None)
            if layer is not None:
                candidates.append((pose.pbd_path.parent / layer.filename, layer.left, layer.top))
    else:
        pose = txt_library[game][character_name].bodies[body_name].pose
        candidates = [(pose.layers[key].image_path, pose.layers[key].left, pose.layers[key].top)
                      for key in pose.faces[face_name]]
    return [box for path, left, top in candidates if (box := layer_visible_box(path, left, top)) is not None]


def expression_preview(game: str, character_name: str, body_name: str, face_name: str, size: int,
                       characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary) -> Image.Image:
    canvas = web_composite_raw(game, character_name, body_name, face_name, characters, lime_characters, txt_library)
    visible = canvas.getchannel("A").getbbox()
    if visible is None:
        raise ValueError("这个组合没有可见像素")
    trim_left = max(0, visible[0] - 4)
    trim_top = max(0, visible[1] - 4)
    trimmed = trim_transparent(canvas)
    boxes = expression_layer_boxes(game, character_name, body_name, face_name, characters, lime_characters, txt_library)
    if boxes:
        focus = (min(box[0] for box in boxes) - trim_left, min(box[1] for box in boxes) - trim_top,
                 max(box[2] for box in boxes) - trim_left, max(box[3] for box in boxes) - trim_top)
        center_x = (focus[0] + focus[2]) / 2
        #预览覆盖头部、肩部与上半身，兼顾表情和服装差异。
        center_y = (focus[1] + focus[3]) / 2 + max(focus[2] - focus[0], focus[3] - focus[1]) * 0.75
        side = max(focus[2] - focus[0], focus[3] - focus[1]) * 3.2
    else:
        #拿不到表情图层框时的兜底：取上半身，而不是取脸部大小。
        center_x = trimmed.width / 2
        center_y = trimmed.height * 0.26
        side = min(trimmed.width, trimmed.height) * 0.7
    #至少给到"画布宽度的 45%"或"可见高度的 45%" —— 太小的裁切必然只剩一张脸。
    side = max(side, trimmed.width * 0.45, trimmed.height * 0.45)
    side = max(64, min(side, trimmed.width, trimmed.height))
    left = max(0, min(trimmed.width - side, center_x - side / 2))
    top = max(0, min(trimmed.height - side, center_y - side / 2))
    crop = trimmed.crop((round(left), round(top), round(left + side), round(top + side)))
    crop.thumbnail((size, size), Image.Resampling.LANCZOS)
    return crop


def validate_custom_batch(items: object, catalog: dict, *, limit: int = 500,
                          normal_only: bool = True) -> list[dict[str, str]]:
    """校验批量清单，仅接受普通立绘组合。"""
    if not isinstance(items, list) or not 1 <= len(items) <= limit:
        raise ValueError(f"请添加 1～{limit} 张立绘后再开始")
    validated = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in ("game", "character", "body", "face")):
            raise ValueError("批量清单格式不正确")
        game, character, body, face = (item[key] for key in ("game", "character", "body", "face"))
        try:
            entry = catalog[game]["characters"][character]
            category = entry["bodyCategories"][body]
            if face not in entry["bodies"][body]:
                raise ValueError("批量清单包含已不存在的组合")
        except KeyError as error:
            raise ValueError("批量清单包含已不存在的组合") from error
        if category != "normal":
            raise ValueError("自选批量只接受普通组合")
        key = game, character, body, face
        if key in seen:
            raise ValueError("批量清单包含重复组合")
        seen.add(key)
        record = dict(zip(("game", "character", "body", "face"), key))
        #把分区一起带上：入库要按真实分区写入，不能一律写 normal。
        record["category"] = category
        validated.append(record)
    return validated


def run_custom_batch(items: list[dict[str, str]], output: Path, job: dict, lock: threading.Lock,
                     characters: dict[str, Character], lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary) -> None:
    rows = []
    errors = []
    try:
        output.mkdir(parents=True, exist_ok=False)
        for index, item in enumerate(items, 1):
            game, character, body, face = (item[key] for key in ("game", "character", "body", "face"))
            with lock:
                job["current"] = f"{game} / {character} / {body} / {face}"
            try:
                #批量导出与其他合成入口共用并发限制，控制峰值内存。
                with _COMPOSE_SLOTS:
                    image = web_composite(game, character, body, face, characters, lime_characters, txt_library)
                directory = output / safe_filename(game) / safe_filename(character)
                directory.mkdir(parents=True, exist_ok=True)
                filename = safe_filename(f"{index:03d}_{character}_{body}_{face}", 120) + ".png"
                destination = directory / filename
                image.save(destination)
                rows.append({"序号": index, "作品": game, "角色": character, "身体/服装/姿势": body, "表情": face,
                             "状态": "成功", "输出文件": str(destination.relative_to(output)), "错误原因": ""})
            except Exception as error:
                errors.append(f"第 {index} 张 {character} / {body} / {face}：{error}")
                rows.append({"序号": index, "作品": game, "角色": character, "身体/服装/姿势": body, "表情": face,
                             "状态": "失败", "输出文件": "", "错误原因": str(error)})
            with lock:
                job["completed"] = index
                job["succeeded"] = index - len(errors)
                job["errors"] = errors[-20:]
        with (output / "batch-manifest.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("序号", "作品", "角色", "身体/服装/姿势", "表情", "状态", "输出文件", "错误原因"))
            writer.writeheader()
            writer.writerows(rows)
        with lock:
            job["state"] = "finished"
            job["current"] = ""
    except Exception as error:
        with lock:
            job["state"] = "failed"
            job["errors"] = errors[-19:] + [f"批量任务中断：{error}"]


def run_library_batch(items: list[dict[str, str]], library: SpriteLibrary, job: dict,
                      lock: threading.Lock, characters: dict[str, Character],
                      lime_characters: dict[str, list[LimePose]], txt_library: TxtLibrary,
                      *, batch_label: str = "", source: str = "批量入库") -> None:
    """在后台合成立绘并入库，合并标签并更新任务进度。"""
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    created = duplicate = 0
    try:
        for index, item in enumerate(items, 1):
            game, character, body, face = (item[key] for key in ("game", "character", "body", "face"))
            category = item.get("category") or "normal"
            with lock:
                job["current"] = f"{character} / {body} / {face}"
            try:
                with _COMPOSE_SLOTS:
                    image = web_composite(game, character, body, face,
                                          characters, lime_characters, txt_library)
                tags = build_auto_tags({**item, "category": category},
                                       batch_label=batch_label, source=source)
                with _LIBRARY_WRITE_LOCK:
                    result = library.save(game, character, body, face, category, image, tags)
                if result.get("created"):
                    created += 1
                else:
                    duplicate += 1
                rows.append({"序号": index, "作品": game, "角色": character,
                             "身体/服装/姿势": body, "表情": face, "状态": "已入库",
                             "标签": " ".join(result.get("tags") or []), "错误原因": ""})
            except Exception as error:
                errors.append(f"第 {index} 张 {character} / {body} / {face}：{error}")
                rows.append({"序号": index, "作品": game, "角色": character,
                             "身体/服装/姿势": body, "表情": face, "状态": "失败",
                             "标签": "", "错误原因": str(error)})
            with lock:
                job["completed"] = index
                job["succeeded"] = index - len(errors)
                job["created"] = created
                job["duplicate"] = duplicate
                job["errors"] = errors[-20:]
        #清单落盘：千张级别的批量要能事后对账（哪些进了、哪些是重复）
        try:
            manifest_dir = library.root.parent / app_paths.BATCH_DIR_NAME
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest = manifest_dir / f"library-import-{datetime.now():%Y%m%d-%H%M%S}.csv"
            with manifest.open("x", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("序号", "作品", "角色", "身体/服装/姿势",
                                                            "表情", "状态", "标签", "错误原因"))
                writer.writeheader()
                writer.writerows(rows)
            with lock:
                job["manifest"] = str(manifest)
        except Exception as error:
            _startup_log(f"批量入库清单写入失败（不影响入库结果）：{error!r}")
        with lock:
            job["state"] = "finished"
            job["current"] = ""
    except Exception as error:
        with lock:
            job["state"] = "failed"
            job["errors"] = errors[-19:] + [f"批量入库中断：{error}"]


def validate_library_batch(items: object, catalog: dict) -> list[dict[str, str]]:
    """检查批量入库清单，拒绝当前策略不允许的类别与组合。"""
    return validate_custom_batch(items, catalog, normal_only=False)


def exports_root(code_dir: Path) -> Path:
    return code_dir / "工作数据" / "exports"


def save_single_export(image: Image.Image, directory: Path, character: str, body: str, face: str) -> Path:
    #文件名长度要算上目标目录，否则长角色名 + 长导出目录会撞 MAX_PATH(260)。
    budget = max(40, 240 - len(str(directory)))
    stem = safe_filename(f"{character}_{body}_{face}", min(110, budget))
    destination = directory / f"{stem}_{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.png"
    try:
        with destination.open("xb") as stream:
            image.save(stream, format="PNG")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


class BootState:
    """锁保护的启动共享状态，用于服务先启动、素材后台扫描。"""

    def __init__(self, data_dir: Path, output_root: Path) -> None:
        self.data_dir = data_dir
        self.output_root = output_root
        self.ready = threading.Event()
        self.condition = threading.Condition()
        self.phase = 0
        self.phase_text = "让我先醒一醒……"
        self.done = 0
        self.total = 0
        self.error = ""
        #扫描结果（就绪后才有值）
        self.characters: dict = {}
        self.lime_characters: dict = {}
        self.txt_library: TxtLibrary = {}
        self.policy: IsolationPolicy | None = None
        #缩短测试等待上限，验证未就绪时返回 503。
        self.gate_timeout: list[float] = [8.0]

    def set_phase(self, phase: int, text: str) -> None:
        with self.condition:
            self.phase = max(self.phase, int(phase))
            self.phase_text = text
            self.condition.notify_all()

    def set_progress(self, done: int, total: int) -> None:
        with self.condition:
            self.done = int(done)
            self.total = int(total)
            self.condition.notify_all()

    def fail(self, message: str) -> None:
        with self.condition:
            self.error = str(message)
            self.phase = 3
            self.phase_text = "好啦，进来吧～"
            self.condition.notify_all()
        self.ready.set()

    def publish(self, characters: dict, lime_characters: dict, txt_library: TxtLibrary,
                policy: IsolationPolicy) -> None:
        with self.condition:
            self.characters = characters
            self.lime_characters = lime_characters
            self.txt_library = txt_library
            self.policy = policy
            self.phase = 3
            self.phase_text = "好啦，进来吧～"
            self.condition.notify_all()
        self.ready.set()

    def snapshot(self) -> dict:
        with self.condition:
            return {
                "ready": self.ready.is_set(),
                "phase": self.phase,
                "phaseText": self.phase_text,
                "done": self.done,
                "total": self.total,
                "error": self.error,
            }

    def wait_ready(self, timeout: float = 8.0) -> bool:
        """等扫描完成。返回 False 表示超时（调用方应回 503 而不是挂死）。"""
        return self.ready.wait(timeout)


def perform_scan(state: BootState) -> None:
    """后台扫描素材并读写缓存，完成后发布目录与诊断状态。"""
    data_dir = state.data_dir
    try:
        state.set_phase(0, "让我先醒一醒……")
        try:
            register_bundled_packs(data_dir)
        except Exception as error:
            _startup_log(f"登记内置素材包失败（不影响手动导入）：{error!r}")

        code_dir = app_paths.project_root()
        pack_roots = discover_pack_game_roots(code_dir)
        local_games = game_directories(pack_roots)
        _boot_mark(f"素材目录发现完成（{len(pack_roots)} 个根）")
        state.set_phase(1, "正在把立绘一张张理出来")

        source_root = local_games.get("常轨脱离", code_dir / "常轨脱离")
        lime_root = local_games.get("LimeLightLemonadeJam", code_dir / "LimeLightLemonadeJam")
        scan_roots = list(pack_roots)

        characters, lime_characters, txt_library = run_scan_pipeline(state, data_dir, scan_roots,
                                                                    source_root, lime_root)
        state.set_phase(2, "本地服务开好了")
        #隔离策略损坏时回退默认策略，并在日志中记录。
        try:
            policy = IsolationPolicy.load(state.output_root / app_paths.ISOLATION_DECISIONS_NAME)
        except Exception as error:
            _startup_log(f"隔离审核决定读取失败，已按空策略继续（素材不受隔离限制）：{error!r}")
            policy = IsolationPolicy()
        state.publish(characters, lime_characters, txt_library, policy)
        _startup_log("扫描流水线完成，catalog 数据已就绪")
    except Exception as error:
        _startup_log(f"启动扫描失败：{error!r}")
        state.fail(f"扫描素材时出错：{error}")


def run_scan_pipeline(state: BootState, data_dir: Path, scan_roots: list[Path],
                      source_root: Path, lime_root: Path):
    """扫描/缓存/汇总/写扫描摘要。返回 (characters, lime_characters, txt_library)。"""
    media_warnings: list[str] = []
    txt_warnings: list[str] = []
    txt_library: TxtLibrary = {}
    characters: dict = {}
    lime_characters: dict = {}

    #素材扫描：优先读缓存
    cached = scan_cache.load(data_dir, scan_roots)
    if cached is not None:
        (characters, lime_characters, txt_library, media_warnings, txt_warnings,
         scan_summary_roots) = cached
        _boot_mark("素材扫描完成（命中缓存）")
        _startup_log(
            "素材扫描：命中缓存，跳过重新扫描"
            f"（PNG角色={len(characters)} Lime角色={len(lime_characters)} TXT作品={len(txt_library)}）"
        )
        state.set_progress(len(txt_library), len(txt_library))
    else:
        #扫描逐文件容错：任何单个坏素材只影响它自己，绝不阻断启动。
        state.set_progress(0, 3)
        try:
            characters = scan_characters(source_root, media_warnings)
        except Exception as error:
            characters = {}
            media_warnings.append(f"{source_root}: PNG 坐标素材扫描失败，已按空处理：{error}")
        state.set_progress(1, 3)
        try:
            lime_characters = scan_lime_poses(lime_root, media_warnings)
        except Exception as error:
            lime_characters = {}
            media_warnings.append(f"{lime_root}: PBD 素材扫描失败，已按空处理：{error}")
        state.set_progress(2, 3)
        for scan_root in scan_roots:
            found, warnings = scan_txt_library(scan_root)
            merge_txt_library(txt_library, found)
            txt_warnings.extend(warnings)
        state.set_progress(3, 3)
        #文件统计只在重扫时计算，并随扫描缓存保存。
        scan_summary_roots: list[dict] = []
        for scan_root in scan_roots:
            pbd_count, txt_count, file_count = _count_scan_media(scan_root)
            scan_summary_roots.append(
                {"path": str(scan_root), "pbd": pbd_count, "txt": txt_count, "files": file_count}
            )
        if scan_cache.save(data_dir, scan_roots, characters, lime_characters, txt_library,
                           media_warnings, txt_warnings, scan_summary_roots):
            _boot_mark("素材扫描完成（重新扫描并写入缓存）")
        else:
            #写缓存失败不该影响启动，但要留下痕迹便于排查。
            _startup_log("素材扫描：写缓存失败（不影响使用，下次启动会重新扫描）")
            _boot_mark("素材扫描完成（重新扫描，缓存写入失败）")

    if media_warnings:
        print(f"立绘素材扫描跳过 {len(media_warnings)} 项：")
        for warning in media_warnings[:10]:
            print(f"  - {warning}")
    if txt_warnings:
        print(f"TXT 素材扫描跳过 {len(txt_warnings)} 项：")
        for warning in txt_warnings[:10]:
            print(f"  - {warning}")
    if txt_library:
        game_count = len(txt_library)
        character_count = sum(len(game) for game in txt_library.values())
        print(f"已读取 TXT 源库：{game_count} 部作品，{character_count} 个角色。")

    #启动诊断：把统计写进日志（值来自重扫时的统计或缓存里存下来的，不再重复遍历）。
    for item in scan_summary_roots:
        _startup_log(
            f"扫描目录 {item.get('path')}：.pbd={item.get('pbd')} "
            f".txt={item.get('txt')} 文件={item.get('files')}"
        )
    _startup_log(f"扫描目录列表（{len(scan_roots)} 个）：" + " | ".join(str(p) for p in scan_roots))
    txt_character_count = sum(len(game) for game in txt_library.values())
    _startup_log(
        f"扫描结果：PNG角色={len(characters)} Lime角色={len(lime_characters)} "
        f"TXT作品={len(txt_library)} TXT角色={txt_character_count} TXT警告={len(txt_warnings)} "
        f"立绘警告={len(media_warnings)} "
        f"进程内存={_process_rss_mb():.1f} MB"
    )
    for warning in media_warnings[:20]:
        _startup_log(f"  立绘警告: {warning}")
    for warning in txt_warnings[:20]:
        _startup_log(f"  TXT警告: {warning}")
    empty_library = not characters and not lime_characters and not txt_library
    if empty_library:
        _startup_log("结论：三个适配器均未发现任何可合成素材（空库）。请核对 sprite-packs 目录结构与链接。")
    _write_scan_summary({
        "scannedAt": datetime.now().isoformat(timespec="seconds"),
        "roots": scan_summary_roots,
        "pngCharacters": len(characters),
        "limeCharacters": len(lime_characters),
        "txtGames": len(txt_library),
        "txtCharacters": txt_character_count,
        "warnings": txt_warnings[:20],
        "mediaWarnings": media_warnings[:20],
        "cached": cached is not None,
        "empty": empty_library,
        "memoryMb": round(_process_rss_mb(), 1),
    })
    if empty_library:
        print(
            "没有在项目目录找到可合成素材，将以空素材库启动。"
            "你可以到设置页「素材包导入」导入素材包后再开始合成。",
            file=sys.stderr,
        )
    return characters, lime_characters, txt_library


def run_web_app(code_dir: Path, state: BootState, open_browser: bool = True,
                scan_in_background: bool = True, gate_on_ready: bool | None = None,
                auto_scan: bool = True) -> None:
    """启动回环 HTTP 服务；生产环境后台扫描，测试可同步准备状态。"""
    if gate_on_ready is None:
        gate_on_ready = scan_in_background
    #缩短测试等待上限，验证未就绪时返回 503。
    #测试里通过属性调小，避免让套件白等。
    gate_timeout = state.gate_timeout
    _boot_mark("进入界面服务准备")
    data_dir = state.data_dir
    output_root = state.output_root
    library = SpriteLibrary(output_root / app_paths.LIBRARY_DIR_NAME)
    def recover_geometry(item):
        try:
            raw = web_composite_raw(item['game'],item['character'],item['body'],item['face'],
                                    state.characters,state.lime_characters,state.txt_library)
            cropped = trim_transparent(raw)
            with Image.open(library.file(item['id'],False)) as stored:
                if stored.size != cropped.size or stored.convert('RGBA').tobytes() != cropped.tobytes():
                    return None
            return json.loads(cropped.info['bingyi_geometry'])
        except (KeyError,ValueError,StopIteration,OSError):
            return None
    production = ProductionAPI(data_dir, output_root, library, recover_geometry)
    settings = AppSettings(data_dir)
    jobs: dict[str, dict] = {}
    jobs_lock = threading.Lock()
    #数据就绪后才算得出来的东西（catalog 序列化、策略）放进一个可变盒子
    #服务先监听，盒子稍后由后台线程填。
    box: dict = {"catalog": {}, "catalog_bytes": b"{}", "policy": IsolationPolicy()}
    box_lock = threading.Lock()

    def build_catalog_bytes() -> None:
        """构建并缓存序列化目录数据。"""
        catalog_started = time.perf_counter()
        catalog = web_catalog(state.characters, state.lime_characters, state.txt_library,
                              state.policy or IsolationPolicy(), existing_only=True)
        #Only normal outfits are exposed after removal of special mode.
        for game in catalog.values():
            for character in game["characters"].values():
                character["bodies"] = {body: faces for body, faces in character["bodies"].items()
                                       if character["bodyCategories"][body] == "normal"}
                character["bodyCategories"] = {body: "normal" for body in character["bodies"]}
                character["isolatedBodies"] = []
            game["characters"] = {name: entry for name, entry in game["characters"].items() if entry["bodies"]}
        catalog = {name: game for name, game in catalog.items() if game["characters"]}
        payload = json.dumps(catalog, ensure_ascii=False).encode("utf-8")
        with box_lock:
            box["catalog"] = catalog
            box["catalog_bytes"] = payload
            box["policy"] = state.policy or IsolationPolicy()
        _startup_log(
            f"catalog 构建完成：作品={len(catalog)} "
            f"角色={sum(len(g.get('characters', {})) for g in catalog.values())} "
            f"耗时={(time.perf_counter() - catalog_started) * 1000:.0f} ms "
            f"进程内存={_process_rss_mb():.1f} MB"
        )

    if scan_in_background and auto_scan:
        threading.Thread(target=perform_scan, args=(state,), daemon=True).start()
        threading.Thread(target=lambda: (state.wait_ready(120.0), build_catalog_bytes()), daemon=True).start()
    elif not scan_in_background:
        state.ready.set()
        build_catalog_bytes()
    #每次启动一枚随机令牌，随 GET / 以 cookie 发给页面，POST 必须带上。
    session_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        #读取超时释放半开连接，避免工作线程持续积累。
        timeout = 30

        def log_message(self, _format, *_args):
            return

        def handle_one_request(self):
            """将请求读取超时视为断开，不输出异常堆栈。"""
            try:
                super().handle_one_request()
            except TimeoutError:
                self.close_connection = True
            except OSError:
                self.close_connection = True

        #等待素材就绪设有上限，超时返回 503 供界面重试。
        def _data_ready(self) -> bool:
            if not gate_on_ready:
                return True
            if state.wait_ready(self.gate_timeout[0]):
                return True
            self.send_json({"error": "素材还在准备中，请稍候再试", "booting": True}, 503)
            return False

        def _catalog(self) -> dict:
            with box_lock:
                return box["catalog"]

        def _send_boot(self) -> None:
            snapshot = state.snapshot()
            snapshot["catalogReady"] = bool(self._catalog())
            self.send_json(snapshot)

        #记录请求方法、路径、状态与耗时，错误附带摘要。
        def _record_status(self, status: int) -> None:
            self._last_status = int(status)

        def _begin_request(self, method: str) -> None:
            self._request_method = method
            self._request_timer = time.perf_counter()
            self._last_status = None

        def _end_request(self, path: str, error: str = "") -> None:
            elapsed = (time.perf_counter() - getattr(self, "_request_timer", time.perf_counter())) * 1000
            status = getattr(self, "_last_status", None) or 200
            method = getattr(self, "_request_method", "GET")
            if error:
                _request_log(f"{method} {path} -> {status} ({elapsed:.0f}ms) 异常：{error}")
            else:
                _request_log(f"{method} {path} -> {status} ({elapsed:.0f}ms)")

        def send_response(self, code, message=None):
            self._record_status(code)
            return BaseHTTPRequestHandler.send_response(self, code, message)

        def send_error(self, code, message=None, explain=None):
            self._record_status(code)
            return BaseHTTPRequestHandler.send_error(self, code, message, explain)

        def send_bytes(self, data: bytes, content_type: str, disposition: str | None = None, cache_seconds: int = 0):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if disposition:
                self.send_header("Content-Disposition", disposition)
            if cache_seconds:
                self.send_header("Cache-Control", f"private, max-age={cache_seconds}")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def send_json(self, data: dict, status: int = 200):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                #浏览器提前断开是常态（切页/取消预览），不是错误，不能让它冒到线程栈上。
                pass

        def do_POST(self):
            path = urlparse(self.path).path
            self._begin_request("POST")
            try:
                self._do_post(path)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise
            except Exception as error:  #pragma: no cover
                self._end_request(path, error=repr(error))
                raise
            else:
                self._end_request(path)

        def _do_post(self, path: str):
            if path not in ("/api/custom-batch", "/api/library/save", "/api/library/update",
                            "/api/library/trash", "/api/library/restore", "/api/library/delete",
                            "/api/library/reveal", "/api/settings", "/api/settings/open-folder",
                            "/api/settings/choose-folder", "/api/settings/choose-pack-dir", "/api/export-file",
                            "/api/packs", "/api/data-dir", "/api/picker/open",
                            "/api/settings/cleanup-drag", "/api/diagnostics/export",
                            "/api/library/orphans",
                            "/api/library/batch-save", "/api/library/batch-status",
                            "/api/library/import-pick", "/api/library/import-commit",
                            "/api/rescan") and path not in PRODUCTION_POST_PATHS:
                self.send_error(404)
                return
            #等待素材就绪设有上限，超时返回 503 供界面重试。
            early_ok = {"/api/settings", "/api/settings/open-folder", "/api/settings/choose-folder",
                        "/api/settings/choose-pack-dir", "/api/settings/cleanup-drag",
                        "/api/packs", "/api/data-dir", "/api/picker/open", "/api/rescan",
                        "/api/library/reveal", "/api/library/update", "/api/library/trash",
                        "/api/library/restore", "/api/library/delete",
                        "/api/library/import-pick", "/api/library/import-commit"}
            if path not in early_ok and path not in PRODUCTION_POST_PATHS and not self._data_ready():
                return
            catalog = self._catalog()
            characters = state.characters
            lime_characters = state.lime_characters
            txt_library = state.txt_library
            try:
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("请以 JSON 提交请求")
                origin = self.headers.get("Origin")
                if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                    raise ValueError("请求来源不正确")
                if not _token_ok(self, session_token):
                    self.send_json({"error": "本机会话校验失败，请刷新页面后重试"}, 403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body_limit = 8_000_000 if path in ('/api/script/import', '/api/script/save', '/api/script/generate',
                                                 '/api/roughcut/save', '/api/roughcut/build-script', '/api/roughcut/export','/api/roughcut/rebuild-preview',
                                                 '/api/timeline-voice/generate','/api/timeline-voice/preview') else 262144
                if not 0 < length <= body_limit:
                    raise ValueError("请求大小不正确")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("请求格式不正确")
                if payload.get("special") is True:
                    self.send_json({"error": "特殊界面模式已移除"}, 403)
                    return
                if path in PRODUCTION_POST_PATHS and production.post(self, path, payload):
                    return
                if path == "/api/packs":
                    links_path = app_paths.links_file(data_dir)
                    packs_dir = app_paths.packs_dir()
                    action = payload.get("action")
                    if action == "remove-link":
                        name = str(payload.get("name") or "")
                        self.send_json({"ok": pack_import.remove_link(links_path, name)})
                        return
                    if action == "delete":
                        #多包并存下删除单个作品包；只允许删 sprite-packs 的直接子目录。
                        name = str(payload.get("name") or "")
                        try:
                            pack_import.delete_pack(packs_dir, name)
                        except (ValueError, FileNotFoundError) as error:
                            self.send_json({"error": str(error)}, 400)
                            return
                        scan_cache.clear(data_dir)
                        self.send_json({"ok": True, "name": name, "restartRequired": True})
                        return
                    target = str(payload.get("path") or "").strip()
                    is_zip = Path(target).suffix.lower() in pack_import.ZIP_SUFFIXES
                    #ZIP 与目录分别校验，文件不能进入目录导入校验分支。
                    unsupported = pack_import.unsupported_archive_message(Path(target))
                    if unsupported:
                        self.send_json({"error": unsupported}, 400)
                        return
                    guard_target = str(Path(target).parent) if is_zip else target
                    guard = _reject_dangerous_source(guard_target, code_dir)
                    if guard:
                        self.send_json({"error": guard}, 400)
                        return
                    confirm_update = bool(payload.get("confirmUpdate"))
                    #预检（只读、不写盘）：把包内情况报告给前端，作为"确认"步骤的依据。
                    if action == "preview":
                        self.send_json(pack_import.analyze(target, packs_dir).as_dict())
                        return
                    analysis = pack_import.analyze(target, packs_dir, allow_update=confirm_update)
                    if not analysis.ok:
                        self.send_json(analysis.as_dict(), 400)
                        return
                    if action == "copy":
                        #zip 素材包要走 extract_zip（原子解压），不能当成目录 copytree
                        source = Path(analysis.source_root)
                        if source.suffix.lower() in pack_import.ZIP_SUFFIXES:
                            pack_import.extract_zip(source, packs_dir, analysis.pack_name,
                                                    allow_update=confirm_update)
                        else:
                            pack_import.copy_pack(source, packs_dir)
                    elif action == "link":
                        #链接是"登记一个已解包的素材目录"，zip 得先解压才有目录可登记。
                        source = Path(analysis.source_root)
                        if source.suffix.lower() in pack_import.ZIP_SUFFIXES:
                            self.send_json(
                                {"error": "压缩包请用「复制导入」（程序会解压到 sprite-packs）；"
                                          "「链接导入」只支持已经解包好的素材目录"}, 400)
                            return
                        pack_import.add_link(links_path, source)
                    else:
                        raise ValueError("未知的导入方式")
                    result = analysis.as_dict()
                    result["restartRequired"] = True
                    self.send_json(result, 201)
                    return
                if path == "/api/rescan":
                    #素材扫描结果现在是缓存的（命中缓存时启动从 4.2s 降到 0.5s）。
                    cleared = scan_cache.clear(data_dir)
                    _startup_log(f"用户请求重新扫描素材（清除缓存={cleared}），即将重启程序")
                    self.send_json({"cleared": cleared, "restarting": _schedule_relaunch()})
                    return
                if path == "/api/library/import-pick":
                    #系统多选文件框；在 HTTP 工作线程里跑 Win32 通用对话框（不能用 tkinter）。
                    self.send_json({"paths": file_dialog.browse_for_images()})
                    return
                if path == "/api/library/import-commit":
                    raw_paths = payload.get("paths")
                    if not isinstance(raw_paths, list) or not raw_paths:
                        raise ValueError("请先选择要导入的图片")
                    if len(raw_paths) > 200:
                        raise ValueError("一次最多导入 200 张，请分批进行")
                    character = payload.get("character")
                    game = payload.get("game")
                    #文案刻意不做预先提示（界面没有"必填"标记），不填直接打接口也会吃到同样的话。
                    has_game = bool(str(game or "").strip())
                    has_character = bool(str(character or "").strip())
                    if not has_game and not has_character:
                        raise ValueError(
                            "作品名和角色名都是空的，你这是在玩我，还是在玩 Galgame？"
                            "你自己说说，你推的是哪部作品里的谁，一个都答不上来。"
                            "这工具不是给你囤图的。填了再回来。"
                        )
                    if not has_character:
                        raise ValueError(
                            "作品名填了，角色名空着。"
                            "一个连角色名都懒得打的人，是「不认识」还是「无所谓」？"
                            "玩过 Galgame 的人，会记不住自己推的是谁吗？"
                            "这工具不是给你囤图的。填了再回来。"
                        )
                    if not has_game:
                        raise ValueError(
                            "角色名填了，作品名空着。"
                            "同一个角色在不同作品里的立绘会混成一锅，"
                            "以后你搜出来自己都分不清哪个是哪个。作品名填了再回来。"
                        )
                    tags = payload.get("tags")
                    force = payload.get("force") is True
                    results = []
                    for raw in raw_paths:
                        candidate = Path(str(raw))
                        try:
                            outcome = library.import_image(candidate, character, tags,
                                                           force=force, game=game)
                        except Exception as error:  #单张失败不能拖垮整批
                            _startup_log(f"导入立绘失败 {candidate.name}: {error!r}")
                            outcome = {"name": candidate.name, "status": "rejected",
                                       "reason": f"导入时出错（已记入启动日志）：{_redact_paths(error)}"}
                        results.append(outcome)
                    summary = {
                        "results": results,
                        "imported": sum(1 for r in results if r["status"] == "imported"),
                        "duplicate": sum(1 for r in results if r["status"] == "duplicate"),
                        "warning": sum(1 for r in results if r["status"] == "warning"),
                        "rejected": sum(1 for r in results if r["status"] == "rejected"),
                    }
                    self.send_json(summary, 201 if summary["imported"] else 200)
                    return
                if path == "/api/data-dir":
                    import shutil as _shutil
                    action = payload.get("action")
                    current = app_paths.resolve_data_dir()
                    if action == "set":
                        if not app_paths.is_frozen():
                            raise ValueError("开发态数据目录固定为项目「工作数据」，安装版才可更改")
                        #去掉首尾引号：资源管理器「复制文件地址」给的是带引号的路径，
                        raw = str(payload.get("path") or "").strip().strip('"').strip()
                        if not raw:
                            raise ValueError("请提供目录路径")
                        try:
                            target = Path(raw).expanduser().resolve()
                        except Exception as error:
                            raise ValueError(f"目录路径无法解析：{error}") from error
                        if target.parent == target:
                            raise ValueError("请选择具体的文件夹，不能选整个磁盘根目录")
                        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
                        for blocked in (windows, Path(os.environ.get("ProgramFiles", r"C:\Program Files"))):
                            if blocked.exists() and target.is_relative_to(blocked):
                                raise ValueError("出于安全考虑，不能把数据目录放到系统或程序目录里")
                        if target == code_dir or target.is_relative_to(code_dir):
                            raise ValueError("不能把数据目录放进程序代码目录")
                        if target == current:
                            raise ValueError("这已经是当前的数据目录")
                        if target.is_relative_to(current) or current.is_relative_to(target):
                            raise ValueError("新旧数据目录不能互相包含")
                        #只允许「新建」或「空目录」，避免把用户数据糊进一个不相干的文件夹里。
                        if target.is_dir() and any(target.iterdir()):
                            raise ValueError("目标文件夹不是空的，请换一个新建或空的文件夹")
                        target.mkdir(parents=True, exist_ok=True)
                        #`library.sqlite3` 是 WAL 模式：提交只写进 `-wal`，主库可能只有 4 KB
                        for database in current.glob("*.sqlite3"):
                            try:
                                with sqlite3.connect(database) as connection:
                                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            except Exception as error:
                                _startup_log(f"迁移前整理数据库失败（{database.name}）：{error!r}")
                        copied = failed = skipped = 0
                        for item in current.iterdir():
                            dest = target / item.name
                            if dest.exists():
                                skipped += 1
                                continue
                            try:
                                if item.is_dir():
                                    _shutil.copytree(item, dest)
                                else:
                                    _shutil.copy2(item, dest)
                                copied += 1
                            except Exception as error:
                                failed += 1
                                _startup_log(f"数据目录迁移失败：{item.name} → {error!r}")
                        if failed:
                            raise ValueError(
                                f"迁移中断：{failed} 项复制失败（已成功 {copied} 项）。"
                                "原数据目录没有被改动、指针也没切换，可以修好磁盘后重试；"
                                "重试会自动跳过已经复制好的部分。"
                            )
                        #复制完成后做一次存在性核对，再切指针。
                        missing = [item.name for item in current.iterdir() if not (target / item.name).exists()]
                        if missing:
                            raise ValueError(f"迁移校验失败：{len(missing)} 项没有复制成功（例如 {missing[0]}），"
                                             "指针未切换，原数据目录仍在使用。")
                        #存在性不够：库文件"在"不等于"能用"。逐个打开确认 sprites 表可读，
                        #不通过就不切指针（旧目录继续可用，用户的库不会凭空消失）。
                        for database in target.glob("*.sqlite3"):
                            try:
                                with sqlite3.connect(database) as connection:
                                    connection.execute("SELECT COUNT(*) FROM sprites").fetchone()
                            except sqlite3.DatabaseError as error:
                                raise ValueError(
                                    f"迁移校验失败：新目录里的 {database.name} 无法读取（{error}）。"
                                    "指针未切换，原数据目录仍在使用。"
                                ) from error
                        app_paths.set_custom_data_dir(target)
                        self.send_json({"ok": True, "current": str(target), "restartRequired": True,
                                        "copied": copied, "skipped": skipped})
                        return
                    if action == "reset":
                        app_paths.clear_custom_data_dir()
                        self.send_json({"ok": True, "current": str(app_paths.resolve_data_dir()), "restartRequired": True})
                        return
                    if action == "open":
                        if os.name != "nt":
                            raise ValueError("打开文件夹目前仅支持 Windows")
                        os.startfile(current)  #type: ignore[attr-defined]
                        self.send_json({"ok": True, "path": str(current)})
                        return
                    raise ValueError("未知操作")
                if path == "/api/settings":
                    self.send_json(settings.save(payload))
                    return
                if path == "/api/settings/open-folder":
                    target = payload.get("target")
                    if target == "dir":
                        #打开页面刚刚落盘的那个目录（单张导出后「打开文件夹」用）
                        candidate = Path(str(payload.get("path") or "")).resolve()
                        if not candidate.is_dir():
                            raise ValueError("文件夹不存在")
                        folder = candidate
                    elif target == "app-file":
                        #许可文件只接受白名单名称；Windows 使用 LICENSE.txt 副本。
                        name = str(payload.get("name") or "")
                        if name not in _OPENABLE_PROJECT_FILES:
                            raise ValueError("只能打开程序自带的说明文件")
                        folder = app_paths.project_root() / name
                        if not folder.is_file() and name == "LICENSE.txt":
                            #兼容：老安装包 / 开发态源码里只有无扩展名的 `LICENSE`。
                            legacy = app_paths.project_root() / "LICENSE"
                            if legacy.is_file():
                                folder = legacy
                        if not folder.is_file():
                            raise ValueError(
                                f"程序目录里没有 {name}。源码里一定有此文件，"
                                "安装版请重新安装以恢复文档")
                    else:
                        folder = settings.open_directory(target)
                    if os.name != "nt":
                        raise ValueError("打开文件夹目前仅支持 Windows")
                    os.startfile(folder)
                    self.send_json({"path": str(folder)})
                    return
                if path == "/api/settings/choose-folder":
                    target = payload.get("target")
                    if target in (None, "draft", "episode"):
                        from app_settings import browse_for_directory
                        initial = str(payload.get("initial") or "")
                        if not initial or not Path(initial).is_dir():
                            initial = str(data_dir)
                        title = "选择剪映草稿目录" if target == "draft" else "选择文件夹"
                        selected = browse_for_directory(title, initial)
                    else:
                        selected = settings.choose_directory(target)
                    self.send_json({"path": str(selected) if selected else ""})
                    return
                if path == "/api/settings/choose-pack-dir":
                    selected = file_dialog.browse_for_zip("选择素材包压缩包（.zip）")
                    self.send_json({"path": selected})
                    return
                if path == "/api/settings/cleanup-drag":
                    #拖出目录只在用户显式点"立即清理"时才删：剪映/PR 按路径引用素材，
                    removed = settings.cleanup_drag_directory()
                    self.send_json({"removed": removed, "dir": str(settings.drag_directory())})
                    return
                if path == "/api/library/orphans":
                    #写缩略图，最后 INSERT"，中途被杀就留下没有记录的文件。
                    action = str(payload.get("action") or "scan")
                    found = library._collect_orphans()
                    paths = [*found["images"], *found["thumbs"]]

                    def _size_of(items: list[Path]) -> int:
                        total = 0
                        for item in items:
                            try:
                                total += item.stat().st_size
                            except OSError:
                                continue
                        return total

                    if action == "scan":
                        self.send_json({
                            "images": len(found["images"]),
                            "thumbs": len(found["thumbs"]),
                            "total": len(paths),
                            "bytes": _size_of(paths),
                            #只给前 20 个名字做预览，不把上千条路径塞给前端
                            "preview": [item.name for item in paths[:20]],
                        })
                        return
                    if action == "clean":
                        if not paths:
                            self.send_json({"removed": 0, "bytes": 0, "total": 0})
                            return
                        freed = _size_of(paths)
                        removed = library.delete_orphans(paths)
                        _startup_log(f"用户清理未入库文件：删除 {removed} 个，释放 {freed} 字节")
                        self.send_json({"removed": removed, "bytes": freed, "total": len(paths)})
                        return
                    raise ValueError("未知的清理动作")
                if path == "/api/diagnostics/export":
                    archive = build_diagnostics_archive(data_dir, output_root, settings, self._catalog(), library)
                    self.send_json({
                        "path": str(archive),
                        "dir": str(archive.parent),
                        "name": archive.name,
                        "size": archive.stat().st_size,
                    }, 201)
                    return
                if path == "/api/export-file":
                    game, character, body, face = (payload[key] for key in ("game", "character", "body", "face"))
                    if any(not isinstance(value, str) for value in (game, character, body, face)):
                        raise ValueError("立绘组合格式不正确")
                    entry = self._catalog().get(game, {}).get("characters", {}).get(character)
                    if entry is None or face not in entry["bodies"].get(body, []):
                        raise ValueError("立绘组合不存在")
                    if (entry["bodyCategories"][body] != "normal") != (payload.get("special") is True):
                        raise ValueError("请先切换到对应的界面模式")
                    directory = settings.single_directory()
                    with _COMPOSE_SLOTS:
                        image = web_composite(game, character, body, face, state.characters, state.lime_characters, state.txt_library)
                        saved_path = save_single_export(image, directory, character, body, face)
                    #"已发送到浏览器下载"，文件根本找不到）。
                    self.send_json({
                        "path": str(saved_path),
                        "dir": str(directory),
                        "name": saved_path.name,
                        "size": saved_path.stat().st_size if saved_path.exists() else 0,
                    }, 201)
                    return
                if path == "/api/library/batch-save":
                    #前端用 /api/library/batch-status 轮询进度。
                    items = validate_library_batch(payload["items"], self._catalog())
                    label = payload.get("label")
                    batch_label = label.strip()[:30] if isinstance(label, str) else ""
                    job_id = uuid.uuid4().hex
                    job = {"id": job_id, "state": "running", "total": len(items), "completed": 0,
                           "succeeded": 0, "created": 0, "duplicate": 0, "current": "",
                           "errors": [], "manifest": "", "label": batch_label}
                    with jobs_lock:
                        jobs[job_id] = job
                        if len(jobs) > 30:
                            terminal = [key for key, value in jobs.items()
                                        if value.get("state") in ("finished", "failed") and key != job_id]
                            for key in terminal[:-10]:
                                jobs.pop(key, None)
                    threading.Thread(
                        target=run_library_batch,
                        args=(items, library, job, jobs_lock, state.characters,
                              state.lime_characters, state.txt_library),
                        kwargs={"batch_label": batch_label},
                        daemon=True).start()
                    self.send_json({"id": job_id, "total": len(items)}, 202)
                    return
                if path == "/api/library/batch-status":
                    job_id = str(payload.get("id") or "")
                    with jobs_lock:
                        job = jobs.get(job_id)
                        snapshot = dict(job) if job else None
                    if snapshot is None:
                        self.send_json({"error": "任务不存在"}, 404)
                        return
                    self.send_json(snapshot)
                    return
                if path == "/api/library/save":
                    game, character, body, face = (payload[key] for key in ("game", "character", "body", "face"))
                    if any(not isinstance(value, str) for value in (game, character, body, face)):
                        raise ValueError("立绘组合格式不正确")
                    entry = self._catalog().get(game, {}).get("characters", {}).get(character)
                    if entry is None or face not in entry["bodies"].get(body, []):
                        raise ValueError("立绘组合不存在")
                    category = entry["bodyCategories"][body]
                    if (category != "normal") != (payload.get("special") is True):
                        raise ValueError("请先切换到对应的界面模式")
                    #合成 + 入库（含 PNG 编码、WebP 缩略图、哈希）整体算临界区
                    #单个 TXT/PBD 合成就可能占 80-200 MB，不设限流时多点几下就 OOM。
                    with _COMPOSE_SLOTS:
                        image = web_composite(game, character, body, face, state.characters, state.lime_characters, state.txt_library)
                        #这里再用一把写锁把"查重 + 插入"合成一个原子段（成本可忽略：入库很快）。
                        with _LIBRARY_WRITE_LOCK:
                            result = library.save(game, character, body, face, category, image)
                    self.send_json(result, 201 if result["created"] else 200)
                    return
                if path == "/api/library/update":
                    item = library.update(
                        payload.get("id"), payload.get("special") is True,
                        payload.get("displayName"), payload.get("note"),
                        payload.get("favorite") is True, payload.get("tags"),
                    )
                    if item is None:
                        self.send_json({"error": "立绘不存在或当前模式不可编辑"}, 404)
                        return
                    self.send_json(item)
                    return
                if path == "/api/library/trash":
                    item = library.move_to_trash(payload.get("id"), payload.get("special") is True)
                    if item is None:
                        self.send_json({"error": "立绘不存在或当前模式不可删除"}, 404)
                        return
                    self.send_json(item)
                    return
                if path == "/api/library/restore":
                    item = library.restore(payload.get("id"), payload.get("special") is True)
                    if item is None:
                        self.send_json({"error": "回收站中没有这张立绘或当前模式不可恢复"}, 404)
                        return
                    self.send_json(item)
                    return
                if path == "/api/library/delete":
                    if not library.delete_permanently(payload.get("id"), payload.get("special") is True):
                        self.send_json({"error": "回收站中没有这张立绘或当前模式不可永久删除"}, 404)
                        return
                    self.send_json({"deleted": True})
                    return
                if path == "/api/library/reveal":
                    item_id = payload.get("id")
                    file_path = library.file(item_id, payload.get("special") is True)
                    if file_path is None:
                        self.send_json({"error": "图片不存在或当前模式不可查看"}, 404)
                        return
                    if os.name != "nt":
                        raise ValueError("打开文件夹目前仅支持 Windows")
                    #立绘库一个文件夹里几百上千张，只打开文件夹等于让人再翻一遍。
                    opened = False
                    try:
                        import subprocess
                        subprocess.Popen(["explorer", f"/select,{file_path}"])
                        opened = True
                    except Exception as error:
                        _startup_log(f"选中文件失败，退回只打开文件夹：{error!r}")
                    if not opened:
                        os.startfile(file_path.parent)
                    self.send_json({"path": str(file_path), "selected": opened})
                    return
                if path == "/api/picker/open":
                    import importlib.util
                    import subprocess
                    if os.name != "nt":
                        raise ValueError("冰翼取用精灵目前仅支持 Windows")
                    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    mode = "companion"
                    if getattr(sys, "frozen", False):
                        exe_dir = Path(sys.executable).resolve().parent
                        companion = exe_dir / "IceWingCompanion.exe"
                        fallback = exe_dir / "FloatingPicker.exe"
                        if companion.is_file():
                            subprocess.Popen([str(companion)], cwd=str(exe_dir), creationflags=flags)
                        elif fallback.is_file():
                            mode = "fallback"
                            subprocess.Popen([str(fallback)], cwd=str(exe_dir), creationflags=flags)
                        else:
                            raise ValueError("安装目录中未找到冰翼取用精灵，请重新安装")
                    else:
                        script_dir = Path(__file__).resolve().parent
                        if importlib.util.find_spec("PySide6") is not None:
                            subprocess.Popen([sys.executable, str(script_dir / "desktop_pet.py")],
                                             cwd=str(script_dir), creationflags=flags)
                        else:
                            mode = "fallback"
                            subprocess.Popen([sys.executable, str(script_dir / "floating_picker.py")],
                                             cwd=str(script_dir), creationflags=flags)
                    self.send_json({"ok": True, "mode": mode})
                    return
                items = validate_custom_batch(payload["items"], self._catalog())
                #`customRunning` 只是按钮禁用，脚本/连点/轮询失败后重试都能绕过
                with jobs_lock:
                    running = [key for key, value in jobs.items() if value.get("state") == "running"]
                if running:
                    self.send_json(
                        {"error": "已经有一个批量导出在进行中，等它跑完再开始下一批"}, 409)
                    return
                job_id = uuid.uuid4().hex
                output = settings.batch_directory() / app_paths.BATCH_DIR_NAME / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{job_id[:6]}"
                job = {"id": job_id, "state": "running", "total": len(items), "completed": 0, "succeeded": 0,
                       "current": "", "errors": [], "output": str(output)}
                with jobs_lock:
                    jobs[job_id] = job
                    #不立刻删是因为前端可能还要再轮询一次拿最终状态，删早了会误报「任务不存在」。
                    if len(jobs) > 30:
                        terminal = [key for key, value in jobs.items()
                                    if value.get("state") in ("finished", "failed") and key != job_id]
                        for key in terminal[:-10]:
                            jobs.pop(key, None)
                threading.Thread(target=run_custom_batch,
                                 args=(items, output, job, jobs_lock, state.characters, state.lime_characters, state.txt_library), daemon=True).start()
                self.send_json({"id": job_id}, 202)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": _redact_paths(error)}, 400)
            except Exception as error:
                #日志保留详细异常，响应隐藏本机绝对路径。
                _startup_log(f"POST {path} 失败：{error!r}")
                self.send_json({"error": f"操作失败（原因已记入启动日志）：{_redact_paths(error)}"}, 500)

        def do_GET(self):
            request_path = self.path.split("?", 1)[0]
            icewing_asset_names = {
                "workshop-background.png",
                "brand-ribbon.png",
                "loading-ring.png",
                "snowflake.png",
                #它内侧透明，可以直接套在立绘外。
                "library-frame.png",
            }
            icewing_prefix = "/ui/assets/icewing/"
            if request_path.startswith(icewing_prefix):
                asset_name = request_path[len(icewing_prefix):]
                if asset_name not in icewing_asset_names:
                    self.send_error(404)
                    return
                asset_path = os.path.join(os.path.dirname(__file__), "ui", "assets", "icewing", asset_name)
                try:
                    with open(asset_path, "rb") as asset_file:
                        asset_bytes = asset_file.read()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(asset_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(asset_bytes)
                return

            if request_path == "/ui/workbench.css":
                stylesheet_path = os.path.join(os.path.dirname(__file__), "ui", "workbench.css")
                try:
                    with open(stylesheet_path, "rb") as stylesheet_file:
                        stylesheet_bytes = stylesheet_file.read()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(stylesheet_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(stylesheet_bytes)
                return

            parsed = urlparse(self.path)
            self._begin_request("GET")
            try:
                self._do_get(parsed)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise
            except Exception as error:  #pragma: no cover
                self._end_request(parsed.path, error=repr(error))
                raise
            else:
                self._end_request(parsed.path)

        def _do_get(self, parsed):
            if "1" in parse_qs(parsed.query).get("special", []):
                self.send_json({"error": "特殊界面模式已移除"}, 403)
                return
            #加载页与"加载页需要的东西"必须在数据就绪前就能用
            #首页壳（含加载页）、静态资源、/api/boot、以及设置页首屏要用的几个只读接口。
            early_ok = {"/", "/api/boot", "/api/scan-summary", "/api/settings", "/api/brand",
                        "/api/data-dir", "/api/packs"}
            if parsed.path not in early_ok and not parsed.path.startswith("/ui/"):
                if not self._data_ready():
                    return
            catalog = self._catalog()
            characters = state.characters
            lime_characters = state.lime_characters
            txt_library = state.txt_library
            policy = state.policy or IsolationPolicy()
            try:
                if parsed.path == "/":
                    #首页设置会话 cookie，同源请求携带令牌进行写入校验。
                    body = (app_paths.resource_root() / "ui" / "index.html").read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header(
                        "Set-Cookie",
                        f"{TOKEN_COOKIE}={session_token}; Path=/; SameSite=Strict; HttpOnly",
                    )
                    self.end_headers()
                    self.wfile.write(body)
                    return
                static_files = {
                    "/ui/production.js": ("production.js", "text/javascript; charset=utf-8"),
                    "/ui/production.css": ("production.css", "text/css; charset=utf-8"),
                    "/ui/production_v2.js": ("production_v2.js", "text/javascript; charset=utf-8"),
                    "/ui/local_tts.js": ("local_tts.js", "text/javascript; charset=utf-8"),
                    "/ui/script_voice.js": ("script_voice.js", "text/javascript; charset=utf-8"),
                    "/ui/script_layout.js": ("script_layout.js", "text/javascript; charset=utf-8"),
                    "/ui/script_actors.js": ("script_actors.js", "text/javascript; charset=utf-8"),
                    "/ui/timeline_voice.js": ("timeline_voice.js", "text/javascript; charset=utf-8"),
                    "/ui/script_scenes.js": ("script_scenes.js", "text/javascript; charset=utf-8"),
                    "/ui/draft_workflow.js": ("draft_workflow.js", "text/javascript; charset=utf-8"),
                    "/ui/column_workflow.js": ("column_workflow.js", "text/javascript; charset=utf-8"),
                    "/ui/compact_shell.css": ("compact_shell.css", "text/css; charset=utf-8"),
                    "/ui/configuration_workspace.css": ("configuration_workspace.css", "text/css; charset=utf-8"),
                    "/ui/configuration_workspace.js": ("configuration_workspace.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_workspace.js": ("cut_workspace.js", "text/javascript; charset=utf-8"),
                    "/ui/text_workspace.js": ("text_workspace.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_validation.js": ("cut_validation.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_geometry.js": ("cut_geometry.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_composition.js": ("cut_composition.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_studio.js": ("cut_studio.js", "text/javascript; charset=utf-8"),
                    "/ui/cut_script.js": ("cut_script.js", "text/javascript; charset=utf-8"),
                    "/ui/style.css": ("style.css", "text/css; charset=utf-8"),
                    "/ui/icewing-theme.css": ("icewing-theme.css", "text/css; charset=utf-8"),
                    "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/ui/avatar.png": ("avatar.png", "image/png"),
                    "/ui/mascot-icefox.png": ("mascot-icefox.png", "image/png"),
                    "/ui/avatar-fox-round.png": ("avatar-fox-round.png", "image/png"),
                    "/ui/tool-icefox.png": ("tool-icefox.png", "image/png"),
                    "/ui/favicon.png": ("favicon.png", "image/png"),
                    "/ui/signature.svg": ("signature.svg", "image/svg+xml"),
                    "/ui/brand.json": ("brand.json", "application/json; charset=utf-8"),
                    #加载页 4 段立绘（480×720 压过）
                    "/ui/loading/boot-01-default.png": ("loading/boot-01-default.png", "image/png"),
                    "/ui/loading/boot-02-searching.png": ("loading/boot-02-searching.png", "image/png"),
                    "/ui/loading/boot-03-ready.png": ("loading/boot-03-ready.png", "image/png"),
                    "/ui/loading/boot-04-done.png": ("loading/boot-04-done.png", "image/png"),
                }
                if parsed.path in static_files:
                    filename, content_type = static_files[parsed.path]
                    self.send_bytes((app_paths.resource_root() / "ui" / filename).read_bytes(), content_type)
                    return
                #加载页轮询入口：必须不需要数据，否则页面永远等不到就绪。
                if parsed.path == "/api/boot":
                    self._send_boot()
                    return
                if parsed.path.startswith(("/api/backgrounds", "/api/roughcut", "/api/audio", "/api/localtts", "/api/script", "/api/composition", "/api/timeline-voice")):
                    try:
                        handled = production.get(self, parsed.path, parse_qs(parsed.query))
                    except (ValueError, TypeError) as error:
                        self.send_json({"error": _redact_paths(error)}, 400)
                        return
                    if handled:
                        return
                if parsed.path == "/api/catalog":
                    if not self._data_ready():
                        return
                    with box_lock:
                        payload = box["catalog_bytes"]
                    self.send_bytes(payload, "application/json; charset=utf-8")
                    return
                if parsed.path == "/api/settings":
                    self.send_json(settings.snapshot())
                    return
                if parsed.path == "/api/brand":
                    #顺带把「内测期限」状态一起给出：前端本来就会读这个接口，
                    #合并进去省一次请求（前端启动路径越短越好）。
                    brand_payload = dict(app_paths.brand())
                    brand_payload["beta"] = app_paths.build_stamp()
                    self.send_json(brand_payload)
                    return
                if parsed.path == "/api/packs":
                    links_path = app_paths.links_file(data_dir)
                    packs = [{"name": n, "path": str(p), "source": s}
                             for n, p, s in pack_import.iter_pack_roots(app_paths.packs_dir(), links_path)]
                    self.send_json({"packs": packs})
                    return
                if parsed.path == "/api/data-dir":
                    current = app_paths.resolve_data_dir()
                    default = app_paths.default_data_dir()
                    self.send_json({
                        "current": str(current),
                        "default": str(default),
                        "custom": current != default,
                        "frozen": app_paths.is_frozen(),
                    })
                    return
                if parsed.path == "/api/diagnostics":
                    self.send_json(_diagnostics(data_dir, output_root, state.characters, state.lime_characters,
                                                state.txt_library, library, settings, self._catalog()))
                    return
                if parsed.path == "/api/scan-summary":
                    try:
                        summary_path = app_paths.resolve_data_dir() / app_paths.SCAN_SUMMARY_NAME
                        self.send_json(json.loads(summary_path.read_text(encoding="utf-8")))
                    except Exception:
                        self.send_json({"empty": True, "roots": []})
                    return
                if parsed.path == "/api/library":
                    values = parse_qs(parsed.query)
                    special = values.get("special", [""])[0] == "1"
                    search = values.get("search", [""])[0].strip()[:100]
                    game = values.get("game", [""])[0][:150]
                    character = values.get("character", [""])[0][:150]
                    tag = values.get("tag", [""])[0].strip()[:30]
                    favorite = values.get("favorite", [""])[0] == "1"
                    trash = values.get("trash", [""])[0] == "1"
                    try:
                        offset = max(0, min(int(values.get("offset", ["0"])[0]), 1000000))
                    except (ValueError, TypeError):
                        #参数语法错误是客户端问题，应回 400 而不是落到通用 500「合成失败」。
                        self.send_json({"error": "offset 参数格式不正确"}, 400)
                        return
                    self.send_json(library.list(special, search, game, character, tag, favorite, trash, offset=offset))
                    return
                if parsed.path == "/api/library/image":
                    values = parse_qs(parsed.query)
                    item_id = values.get("id", [""])[0]
                    special = values.get("special", [""])[0] == "1"
                    trash = values.get("trash", [""])[0] == "1"
                    if values.get("size", [""])[0] == "thumb":
                        #special / trash 必须传进去：否则普通模式能取到特殊分区的缩略图
                        thumbnail = library.thumbnail_bytes(item_id, special, trash)
                        if thumbnail is not None:
                            self.send_bytes(thumbnail, "image/webp", cache_seconds=3600)
                            return
                    if values.get("crop", [""])[0] == "head":
                        #「面部模式」用的头部特写。
                        head = library.head_bytes(item_id, special, trash)
                        if head is not None:
                            self.send_bytes(head, "image/png", cache_seconds=3600)
                            return
                    file_path = library.file(item_id, special, trash)
                    if file_path is None:
                        self.send_error(404, "Library image not found")
                        return
                    #回退支：缩略图缺失时只能发原图，但必须带缓存头，
                    #否则图库里每个 tile 每次重渲染都会重新下载整张全分辨率 PNG。
                    self.send_bytes(file_path.read_bytes(), "image/png", cache_seconds=600)
                    return
                if parsed.path == "/api/expression-preview":
                    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                    missing = [key for key in ("game", "character", "body", "face") if key not in query]
                    if missing:
                        self.send_json({"error": f"缺少参数：{'、'.join(missing)}"}, 400)
                        return
                    game, character, body, face = (query[key] for key in ("game", "character", "body", "face"))
                    entry = self._catalog().get(game, {}).get("characters", {}).get(character)
                    if entry is None or face not in entry["bodies"].get(body, []):
                        self.send_error(404, "Expression not found")
                        return
                    if entry["bodyCategories"][body] != "normal" and query.get("special") != "1":
                        self.send_error(403, "Special mode required")
                        return
                    size = 640 if query.get("size") == "detail" else 240
                    cache_key = (game, character, body, face, size)
                    png = None
                    if size == 240:
                        with _PREVIEW_CACHE_LOCK:
                            png = _PREVIEW_CACHE.get(cache_key)
                            if png is not None:
                                _PREVIEW_CACHE.move_to_end(cache_key)
                    if png is None:
                        with _COMPOSE_SLOTS:
                            image = expression_preview(game, character, body, face, size,
                                                       state.characters, state.lime_characters, state.txt_library)
                        buffer = io.BytesIO()
                        image.save(buffer, "PNG")
                        png = buffer.getvalue()
                        if size == 240:
                            with _PREVIEW_CACHE_LOCK:
                                _PREVIEW_CACHE[cache_key] = png
                                _PREVIEW_CACHE.move_to_end(cache_key)
                                while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_MAX:
                                    _PREVIEW_CACHE.popitem(last=False)
                    self.send_bytes(png, "image/png", cache_seconds=3600)
                    return
                if parsed.path == "/api/custom-batch":
                    job_id = parse_qs(parsed.query).get("id", [""])[0]
                    with jobs_lock:
                        job = dict(jobs[job_id]) if job_id in jobs else None
                    if job is None:
                        self.send_json({"error": "批量任务不存在或程序已重启"}, 404)
                    else:
                        self.send_json(job)
                    return
                query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                if parsed.path in ("/api/preview", "/api/export"):
                    missing = [key for key in ("game", "character", "body", "face") if key not in query]
                    if missing:
                        self.send_json({"error": f"缺少参数：{'、'.join(missing)}"}, 400)
                        return
                    #这两个端点是唯一不做存在性校验的合成入口
                    character_entry = (self._catalog().get(query["game"], {})
                                       .get("characters", {}).get(query["character"]))
                    if character_entry is None or query["face"] not in character_entry["bodies"].get(query["body"], []):
                        self.send_json(
                            {"error": f"素材里没有这个组合：{query['game']} / {query['character']} / "
                                      f"{query['body']} / {query['face']}"}, 404)
                        return
                    category = (state.policy or IsolationPolicy()).category(query["game"], query["character"], query["body"])
                    if category != "normal" and query.get("special") != "1":
                        message = "请先进入特殊内容界面".encode("utf-8")
                        self.send_response(403)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header("Content-Length", str(len(message)))
                        self.end_headers()
                        self.wfile.write(message)
                        return
                    with _COMPOSE_SLOTS:
                        image = web_composite(query["game"], query["character"], query["body"], query["face"], state.characters, state.lime_characters, state.txt_library)
                    buffer = io.BytesIO()
                    if parsed.path == "/api/preview":
                        image.save(buffer, "PNG")
                        self.send_bytes(buffer.getvalue(), "image/png")
                    else:
                        image.save(buffer, "PNG")
                        filename = safe_filename(f"{query['character']}_{query['face']}") + ".png"
                        self.send_bytes(buffer.getvalue(), "image/png", f"attachment; filename*=UTF-8''{quote(filename)}")
                    return
                self.send_error(404)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except Exception as error:
                #日志保留详细异常，响应隐藏本机绝对路径。
                _startup_log(f"合成失败：{error!r}")
                message = f"合成失败：{_redact_paths(error)}".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)

    Handler.gate_timeout = gate_timeout  #类属性形式暴露给每个请求实例
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    _boot_mark("本地服务就绪")
    global LAST_URL
    LAST_URL = url
    print(f"冰翼Gal创作工坊正在运行：{url}")
    print("关闭此命令窗口即可停止程序。")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def locate_project_root(script_path: Path) -> Path:
    code_dir = script_path.parent
    candidates = (
        code_dir.parent / "krkr立绘合成工程特殊",
        code_dir.parent,
        Path.cwd(),
    )
    for candidate in candidates:
        if (candidate / "常轨脱离").is_dir() or (candidate / "LimeLightLemonadeJam").is_dir():
            return candidate
    return Path.cwd()


def discover_pack_game_roots(code_dir: Path) -> list[Path]:
    """Return every sprite pack's games directory (builtin + linked)."""
    packs_dir = app_paths.packs_dir()
    roots: list[Path] = []
    def add(root):
        #Older imports accepted the games folder itself, and older zip
        #extraction could flatten that folder into the pack root.
        games_dir = root / "games"
        if not games_dir.is_dir():
            if root.name.casefold() == 'games' or any(root.glob('*/*/*.pbd')) or any(root.glob('*/*/*.txt')):
                games_dir = root
            else:
                return
        if games_dir.resolve() not in {p.resolve() for p in roots}:
            roots.append(games_dir)
    if packs_dir.is_dir():
        for pack_dir in sorted((item for item in packs_dir.iterdir() if item.is_dir() and not item.name.startswith('.')), key=lambda item: item.name.casefold()):
            add(pack_dir)
    try:
        links_path = app_paths.links_file(app_paths.resolve_data_dir())
        for _name, root, source in pack_import.iter_pack_roots(packs_dir, links_path):
            if source != "link":
                continue
            add(root)
    except Exception:
        pass
    return roots


def game_directories(roots: Iterable[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for game_dir in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
            result.setdefault(game_dir.name, game_dir)
    return result


def merge_txt_library(target: TxtLibrary, source: TxtLibrary) -> None:
    for game_name, characters in source.items():
        target_game = target.setdefault(game_name, {})
        for character_name, character in characters.items():
            if character_name not in target_game:
                target_game[character_name] = character
                continue
            existing = target_game[character_name]
            for body_name, body in character.bodies.items():
                existing.bodies.setdefault(body_name, body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冰翼Gal创作工坊，本地 KRKR 人物立绘合成器。")
    parser.add_argument("--project-root", type=Path, help="项目根目录；默认自动定位。")
    parser.add_argument("--source-library", type=Path, help="TXT 坐标素材库；默认读取项目旁的 krkr立绘合成工程源库。")
    parser.add_argument("--isolation-report", action="store_true", help="将隔离候选写入工作数据/exports 下的审核清单。")
    parser.add_argument("--no-browser", action="store_true", help="启动本地网页服务但不自动打开浏览器。")
    parser.add_argument("--scan-first", action="store_true",
                        help="先扫描再起服务（旧行为，仅用于排查启动问题）。")
    arguments = parser.parse_args(argv)

    _boot_mark("入口与参数解析完成")
    script_path = Path(__file__).resolve()
    code_dir = script_path.parent
    data_dir = app_paths.resolve_data_dir()
    _boot_mark("数据目录就绪")
    _flush_boot_marks()
    _trim_startup_log()
    try:
        _startup_log("[boot] 机器画像：" + " / ".join(_machine_profile_lines()))
    except Exception:
        pass
    output_root = data_dir / "exports"
    state = BootState(data_dir, output_root)

    if arguments.isolation_report:
        #离线报告是命令行工具，不需要窗口：同步扫完再出清单。
        perform_scan(state)
        if not state.ready.wait(180):
            print("扫描超时，无法生成隔离候选清单。", file=sys.stderr)
            return 1
        catalog = web_catalog(state.characters, state.lime_characters, state.txt_library,
                              state.policy or IsolationPolicy(), existing_only=True)
        destination = output_root / app_paths.ISOLATION_DIR_NAME / (
            f"isolation-candidates-{datetime.now():%Y%m%d-%H%M%S-%f}.csv")
        count = write_isolation_report(catalog, destination, state.policy or IsolationPolicy())
        print(f"已列出 {count} 个待人工审核的完整组合：{destination}")
        return 0

    #扫描在后台线程里跑，页面用 /api/boot 显示真实进度。
    run_web_app(code_dir, state, open_browser=not arguments.no_browser,
                scan_in_background=not arguments.scan_first)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
