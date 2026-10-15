"""检查并原子导入素材 ZIP 或目录；拒绝越界路径和超量解压。"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MEDIA_SUFFIXES = {".pbd", ".txt"}
PNG_SUFFIX = ".png"
ZIP_SUFFIXES = {".zip"}
UNSUPPORTED_ARCHIVE_SUFFIXES = {".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab", ".iso"}



POSITION_RE = re.compile(r"pos,(-?\d+),(-?\d+),(\d+),(\d+)")

PNG_POSITION_SAMPLE_PER_CHARACTER = 3
PNG_POSITION_SAMPLE_MAX = 60


MAX_ZIP_ENTRIES = 200_000
MAX_ZIP_TOTAL_BYTES = 12 * 1024 * 1024 * 1024
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
)


def unsupported_archive_message(path: Path) -> str | None:
    """非 zip 的常见归档：返回给用户的明确提示；不是归档则返回 None。"""
    suffix = path.suffix.lower()
    if suffix in UNSUPPORTED_ARCHIVE_SUFFIXES:
        return f"暂不支持 {suffix} 格式，请先解压后重新压成 .zip 再导入。"
    return None


def _safe_member(name: str) -> str | None:
    """规整 ZIP 相对路径，拒绝绝对路径、父级跳转、ADS 与设备名。"""
    cleaned = name.replace("\\", "/").lstrip("/")
    if not cleaned:
        return None
    parts: list[str] = []
    for part in cleaned.split("/"):
        if part in ("", "."):
            continue
        if part == ".." or ":" in part:
            return None
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            return None
        parts.append(part)
    return "/".join(parts) or None


def _games_from_members(names: list[str]) -> list[str]:
    """从 zip 条目名里解析出 `games/<作品名>` 的作品名（去重、排序）。"""
    games: set[str] = set()
    for name in names:
        parts = name.split("/")
        for index, part in enumerate(parts):
            if part.casefold() == "games" and index + 1 < len(parts):
                candidate = parts[index + 1]
                if candidate:
                    games.add(candidate)
                break
    return sorted(games)


def _sample_names(names: list[str], per_dir: int, cap: int) -> list[str]:
    """按目录分层抽样：每个目录最多 per_dir 个，总量超过 cap 时均匀稀释。"""
    groups: dict[str, list[str]] = {}
    for name in names:
        directory = name.rsplit("/", 1)[0] if "/" in name else ""
        groups.setdefault(directory, []).append(name)
    sample: list[str] = []
    for directory in sorted(groups):
        sample.extend(sorted(groups[directory])[:per_dir])
    if len(sample) > cap:
        step = len(sample) / cap
        sample = [sample[int(index * step)] for index in range(cap)]
    return sample


def _archive_png_has_position(archive: zipfile.ZipFile, name: str) -> bool:
    try:
        from PIL import Image

        with archive.open(name) as handle:
            with Image.open(handle) as image:
                comment = image.info.get("comment", "")
        if isinstance(comment, bytes):
            comment = comment.decode("utf-8", errors="replace")
        return bool(POSITION_RE.search(str(comment)))
    except Exception:
        return False


def inspect_zip(zip_path: Path) -> tuple[dict, list[str]]:
    """只读检查 ZIP 的文件类型、坐标元数据与资源上限，返回统计和错误。"""
    stats = {"pbd": 0, "txt": 0, "png": 0, "files": 0, "bytes": 0,
             "games": [], "pngPositionOk": False, "pngChecked": 0}
    errors: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                errors.append(f"压缩包内条目过多（{len(infos)} 个），超过 {MAX_ZIP_ENTRIES} 上限")
                return stats, errors
            total = 0
            bad: list[str] = []
            png_names: list[str] = []
            for info in infos:
                if info.is_dir():
                    continue
                if _safe_member(info.filename) is None:
                    bad.append(info.filename)
                    continue
                stats["files"] += 1
                total += info.file_size
                suffix = Path(info.filename).suffix.lower()
                if suffix in MEDIA_SUFFIXES:
                    stats["bytes"] += info.file_size
                    if suffix == ".pbd":
                        stats["pbd"] += 1
                    else:
                        stats["txt"] += 1
                elif suffix == PNG_SUFFIX:
                    png_names.append(info.filename)
            stats["png"] = len(png_names)
            stats["games"] = _games_from_members([i.filename for i in infos if not i.is_dir()])
            if total > MAX_ZIP_TOTAL_BYTES:
                errors.append(f"解压后体积过大（{total / 1073741824:.1f} GB），拒绝解压")
            if bad:
                errors.append(f"压缩包内含不安全路径（{len(bad)} 条），已拒绝：{bad[0]}")

            if not errors and not (stats["pbd"] or stats["txt"]) and png_names:
                sample = _sample_names(png_names, PNG_POSITION_SAMPLE_PER_CHARACTER, PNG_POSITION_SAMPLE_MAX)
                stats["pngChecked"] = len(sample)
                stats["pngPositionOk"] = any(_archive_png_has_position(archive, n) for n in sample)
    except zipfile.BadZipFile:
        errors.append("这个文件不是有效的 zip（可能下载不完整或已损坏）")
    except OSError as error:
        errors.append(f"读取压缩包失败：{error}")
    return stats, errors


def _normalize_single_top(staging: Path) -> None:
    """剥离唯一顶层包装目录，将实际素材内容提升为包根。"""
    children = list(staging.iterdir())
    if (len(children) == 1 and children[0].is_dir()
            and children[0].name.casefold() != "games"
            and (children[0] / "games").is_dir()):
        inner = children[0]
        for item in list(inner.iterdir()):
            item.rename(staging / item.name)
        inner.rmdir()


def _replace_dir(source: Path, target: Path) -> None:
    """用新目录原子替换目标；就位失败时恢复原目录。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        os.replace(source, target)
        return
    old = target.with_name(f"{target.name}.old-{uuid.uuid4().hex}")
    os.replace(target, old)
    try:
        os.replace(source, target)
    except Exception:
        os.replace(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def _merge_into_existing(staging: Path, target: Path) -> None:
    """把 staging 按「作品粒度」合并进已存在的 target（同作品覆盖、新作品新增）。"""
    staged_games = staging / "games"
    if staged_games.is_dir():
        target_games = target / "games"
        target_games.mkdir(parents=True, exist_ok=True)
        for game in sorted(staged_games.iterdir()):
            if game.is_dir():
                _replace_dir(game, target_games / game.name)

    for item in list(staging.iterdir()):
        if item.name == "games":
            continue
        destination = target / item.name
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            os.replace(item, destination)
        else:
            if destination.exists():
                destination.unlink()
            os.replace(item, destination)
    shutil.rmtree(staging, ignore_errors=True)


def extract_zip(zip_path: Path, packs_dir: Path, pack_name: str | None = None, *,
                allow_update: bool = False, progress=None) -> Path:
    """先解压到临时目录，再整体发布；失败时清理临时内容。"""
    name = (pack_name or zip_path.stem).strip() or zip_path.stem
    safe = _safe_member(name)
    if safe is None or "/" in safe:
        raise ValueError("包名不合法，请改用字母、数字、中文或 - _ 组合")
    target = packs_dir / safe
    exists = target.exists()
    if exists and not allow_update:
        raise FileExistsError(f"sprite-packs 中已存在同名目录「{safe}」，为避免覆盖已拒绝")

    packs_dir.mkdir(parents=True, exist_ok=True)
    staging = packs_dir / f".tmp-{uuid.uuid4().hex}"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            total = sum(info.file_size for info in infos)
            if total > MAX_ZIP_TOTAL_BYTES:
                raise ValueError(f"解压后体积过大（{total / 1073741824:.1f} GB），拒绝解压")
            count = len(infos)
            for index, info in enumerate(infos, start=1):
                member = _safe_member(info.filename)
                if member is None:
                    raise ValueError(f"压缩包内含不安全路径，已拒绝：{info.filename}")
                destination = staging / member
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)
                if progress is not None:
                    try:
                        progress(index, count)
                    except Exception:
                        pass

        _normalize_single_top(staging)
        if exists:
            _merge_into_existing(staging, target)
        else:
            os.replace(staging, target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def delete_pack(packs_dir: Path, name: str) -> bool:
    """只删除素材根的直接子目录，拒绝临时目录与越界名称。"""
    safe = _safe_member(name)
    if safe is None or "/" in safe or safe.startswith("."):
        raise ValueError("包名不合法")
    target = packs_dir / safe
    if not target.exists():
        raise FileNotFoundError(f"sprite-packs 中不存在素材包「{safe}」")
    if not target.is_dir():
        raise ValueError(f"「{safe}」不是一个素材包目录")
    shutil.rmtree(target)
    return True


@dataclass
class PackAnalysis:
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    pack_name: str = ""
    source_root: str = ""
    pbd_count: int = 0
    txt_count: int = 0
    png_count: int = 0
    file_count: int = 0
    total_bytes: int = 0
    games: list[str] = field(default_factory=list)
    existing: bool = False
    png_position_ok: bool = False
    png_checked: int = 0

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "packName": self.pack_name,
            "sourceRoot": self.source_root,
            "pbdCount": self.pbd_count,
            "txtCount": self.txt_count,
            "pngCount": self.png_count,
            "fileCount": self.file_count,
            "totalBytes": self.total_bytes,
            "games": self.games,
            "existing": self.existing,
            "pngPositionOk": self.png_position_ok,
            "pngChecked": self.png_checked,
        }


def _count_media(root: Path) -> tuple[int, int, int, int]:
    pbd = txt = files = size = 0
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        files += 1
        suffix = item.suffix.lower()
        if suffix in MEDIA_SUFFIXES:
            try:
                size += item.stat().st_size
            except OSError:
                pass
            if suffix == ".pbd":
                pbd += 1
            else:
                txt += 1
    return pbd, txt, files, size


def _png_has_position(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as image:
            comment = image.info.get("comment", "")
        if isinstance(comment, bytes):
            comment = comment.decode("utf-8", errors="replace")
        return bool(POSITION_RE.search(str(comment)))
    except Exception:
        return False


def _dir_png_position_ok(root: Path) -> bool:
    """目录形态的 png-position-v1 抽样检查：任一样本带坐标即视为合格。"""
    pngs = sorted(root.rglob(f"*{PNG_SUFFIX}"))
    if not pngs:
        return False
    groups: dict[Path, list[Path]] = {}
    for path in pngs:
        groups.setdefault(path.parent, []).append(path)
    sample: list[Path] = []
    for parent in sorted(groups, key=lambda p: str(p)):
        sample.extend(sorted(groups[parent], key=lambda p: p.name)[:PNG_POSITION_SAMPLE_PER_CHARACTER])
    if len(sample) > PNG_POSITION_SAMPLE_MAX:
        step = len(sample) / PNG_POSITION_SAMPLE_MAX
        sample = [sample[int(index * step)] for index in range(PNG_POSITION_SAMPLE_MAX)]
    return any(_png_has_position(path) for path in sample)


def _dir_games(root: Path) -> list[str]:
    games_dir = root / "games"
    if games_dir.is_dir():
        return sorted(child.name for child in games_dir.iterdir() if child.is_dir())

    return sorted(child.name for child in root.iterdir() if child.is_dir())


def _normalize_source(path: Path) -> tuple[Path | None, str]:
    """返回 (包根目录, 错误信息)。允许用户选中包根本身或它的单层父目录。"""
    if not path.exists():
        return None, "目录不存在"
    if not path.is_dir():
        return None, "所选路径不是目录"
    if _content_ok(path):
        return path, ""
    children = [c for c in path.iterdir() if c.is_dir()]
    if len(children) == 1 and _content_ok(children[0]):
        return children[0], ""
    return None, "未找到素材内容：目录（或其唯一子目录）中没有 .pbd / .txt / 带坐标的 PNG 文件"


def _content_ok(root: Path) -> bool:
    pbd, txt, _, _ = _count_media(root)
    return bool(pbd or txt) or _dir_png_position_ok(root)


def analyze(path_str: str, packs_dir: Path | None = None, *, allow_update: bool = False) -> PackAnalysis:
    result = PackAnalysis()
    try:
        path = Path(path_str).expanduser().resolve()
    except Exception:
        result.errors.append("路径无法解析")
        return result

    unsupported = unsupported_archive_message(path)
    if unsupported:
        result.errors.append(unsupported)
        return result


    if path.suffix.lower() in ZIP_SUFFIXES and path.is_file():
        stats, errors = inspect_zip(path)
        result.errors.extend(errors)
        result.pack_name = path.stem
        result.source_root = str(path)
        result.pbd_count = stats["pbd"]
        result.txt_count = stats["txt"]
        result.png_count = stats["png"]
        result.file_count = stats["files"]
        result.total_bytes = stats["bytes"]
        result.games = list(stats["games"])
        result.png_position_ok = bool(stats["pngPositionOk"])
        result.png_checked = int(stats["pngChecked"])
        if errors:
            return result
        if not (stats["pbd"] or stats["txt"]):
            if stats["png"] and stats["pngPositionOk"]:
                pass
            elif stats["png"]:
                result.errors.append(
                    "这个压缩包里全是图片，但抽样检查发现 PNG 里没有 pos 坐标元数据，"
                    "无法用于合成（png-position-v1 要求坐标写在 PNG 注释里）。"
                )
                return result
            else:
                result.errors.append("压缩包里没有找到素材内容（没有任何 .pbd / .txt / 带坐标的 PNG 文件）")
                return result
        if packs_dir is not None and (packs_dir / path.stem).exists():
            result.existing = True
            if not allow_update:
                result.errors.append(f"sprite-packs 中已存在同名目录「{path.stem}」，为避免覆盖已拒绝")
                return result
        result.ok = True
        return result

    root, error = _normalize_source(path)
    if root is None:
        result.errors.append(error)
        return result
    if packs_dir is not None:
        packs_root = packs_dir.resolve()
        selected = root.resolve()
        if (selected == packs_root or selected.is_relative_to(packs_root)
                or packs_root.is_relative_to(selected)):
            result.errors.append("这是程序自身的素材目录，无需导入，程序会自动读取")
            return result
    result.pack_name = root.name
    result.source_root = str(root)
    result.pbd_count, result.txt_count, result.file_count, result.total_bytes = _count_media(root)
    result.png_count = sum(1 for _ in root.rglob(f"*{PNG_SUFFIX}"))
    result.games = _dir_games(root)
    if not (result.pbd_count or result.txt_count):
        result.png_position_ok = _dir_png_position_ok(root)
    if packs_dir is not None and (packs_dir / result.pack_name).exists():
        result.existing = True
        if not allow_update:
            result.errors.append(f"sprite-packs 中已存在同名目录「{result.pack_name}」，为避免覆盖已拒绝")
            return result
    result.ok = True
    return result


def copy_pack(source_root: Path, packs_dir: Path) -> Path:
    """先完整复制到临时目录，再原子改名；失败不留下半包。"""
    target = packs_dir / source_root.name
    if target.exists():
        raise FileExistsError(f"目标目录已存在：{target}")
    packs_dir.mkdir(parents=True, exist_ok=True)
    staging = packs_dir / f".tmp-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source_root, staging)
        os.replace(staging, target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_links(links_path: Path) -> list[dict]:
    """读取链接清单；不存在返回空列表，损坏或无法读取则抛出异常。"""
    if not links_path.exists():
        return []
    try:
        raw = links_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"链接素材包清单无法读取（{error}）；文件位置：{links_path}") from error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"链接素材包清单已损坏（{error}）；文件位置：{links_path}。"
            f"可以删掉它再重新导入素材包"
        ) from error
    if not isinstance(data, list):
        raise ValueError(f"链接素材包清单格式不正确（应为列表）；文件位置：{links_path}")
    return [item for item in data if isinstance(item, dict) and item.get("path")]



_LINKS_LOCK = threading.Lock()


def save_links(links_path: Path, links: list[dict]) -> None:
    links_path.parent.mkdir(parents=True, exist_ok=True)

    temp = links_path.with_name(f"{links_path.stem}-{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(links_path)
    finally:
        temp.unlink(missing_ok=True)


def add_link(links_path: Path, source_root: Path) -> dict:

    with _LINKS_LOCK:
        links = load_links(links_path)
        for item in links:
            if Path(item["path"]) == source_root:
                return item
        entry = {"name": source_root.name, "path": str(source_root)}
        links.append(entry)
        save_links(links_path, links)
        return entry


def remove_link(links_path: Path, name: str) -> bool:
    with _LINKS_LOCK:
        links = load_links(links_path)
        kept = [item for item in links if item.get("name") != name]
        if len(kept) == len(links):
            return False
        save_links(links_path, kept)
        return True


def iter_pack_roots(packs_dir: Path, links_path: Path) -> list[tuple[str, Path, str]]:
    """合并本地包与链接包；重名优先本地包，坏链接不影响本地扫描。"""
    roots: list[tuple[str, Path, str]] = []
    names: set[str] = set()
    if packs_dir.exists():
        for child in sorted(packs_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                roots.append((child.name, child, "builtin"))
                names.add(child.name)
    try:
        links = load_links(links_path)
    except ValueError:
        return roots
    for item in links:
        path = Path(item["path"])
        name = str(item.get("name") or path.name)
        if name in names or not path.exists():
            continue
        roots.append((name, path, "link"))
        names.add(name)
    return roots
