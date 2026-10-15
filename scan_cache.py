"""按文件路径、大小、修改时间与结构版本缓存素材扫描结果。"""
from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path


SCAN_CACHE_VERSION = 2
CACHE_FILENAME = "scan-cache.pkl"

_FINGERPRINT_SUFFIXES = {".txt", ".sinfo", ".pbd", ".png", ".webp"}


class _CacheUnpickler(pickle.Unpickler):
    """将脚本运行时记录为 __main__ 的类型映射回实际模块。"""

    def find_class(self, module, name):
        if module == "__main__":
            try:
                import sprite_composer as _module

                candidate = getattr(_module, name, None)
                if candidate is not None:
                    return candidate
            except Exception:
                pass
        return super().find_class(module, name)


def cache_path(data_dir: Path) -> Path:
    return Path(data_dir) / CACHE_FILENAME


def fingerprint(roots: list[Path]) -> tuple[str, int]:
    """用相对路径、大小与 mtime_ns 计算指纹，不解析素材内容。"""
    items: list[tuple[str, int, int]] = []
    stack: list[tuple[Path, str]] = [(Path(root), "") for root in roots]
    while stack:
        base, rel = stack.pop()
        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    child_rel = f"{rel}/{entry.name}" if rel else entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((Path(entry.path), child_rel))
                        elif entry.is_file(follow_symlinks=False):
                            if Path(entry.name).suffix.lower() in _FINGERPRINT_SUFFIXES:
                                stat = entry.stat()
                                items.append((child_rel, stat.st_size, stat.st_mtime_ns))
                    except OSError:


                        continue
        except OSError:
            continue
    items.sort()
    digest = hashlib.sha256()
    for row in items:
        digest.update(repr(row).encode("utf-8", "replace"))
    return digest.hexdigest(), len(items)


def load(data_dir: Path, roots: list[Path]):
    """缓存损坏或指纹失效时返回 None，由调用方重新扫描。"""
    path = cache_path(data_dir)
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            payload = _CacheUnpickler(handle).load()
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != SCAN_CACHE_VERSION:
            return None
        if [str(Path(r)) for r in roots] != list(payload.get("roots") or []):
            return None
        digest, count = fingerprint(roots)
        if payload.get("fingerprint") != digest:
            return None
        if payload.get("fileCount") != count:
            return None
        characters = payload.get("characters")
        lime = payload.get("lime")
        txt = payload.get("txt")
        if not isinstance(characters, dict) or not isinstance(lime, dict) or not isinstance(txt, dict):
            return None
        return (
            characters,
            lime,
            txt,
            list(payload.get("mediaWarnings") or []),
            list(payload.get("txtWarnings") or []),


            list(payload.get("scanSummaryRoots") or []),
        )
    except Exception:

        return None


def save(data_dir: Path, roots: list[Path], characters, lime, txt,
         media_warnings: list[str], txt_warnings: list[str],
         scan_summary_roots: list[dict] | None = None) -> bool:
    """写缓存。失败返回 False（绝不抛异常打断启动）。"""
    try:
        digest, count = fingerprint(roots)
        payload = {
            "version": SCAN_CACHE_VERSION,
            "fingerprint": digest,
            "fileCount": count,

            "roots": [str(Path(r)) for r in roots],
            "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scanSummaryRoots": list(scan_summary_roots or []),
            "mediaWarnings": list(media_warnings)[:200],
            "txtWarnings": list(txt_warnings)[:200],
            "characters": characters,
            "lime": lime,
            "txt": txt,
        }
        path = cache_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp, path)
        return True
    except Exception:
        return False


def clear(data_dir: Path) -> bool:
    """删除缓存（供设置页「重新扫描素材」用）。返回是否真的删掉了。"""
    try:
        path = cache_path(data_dir)
        if path.is_file():
            path.unlink()
            return True
        return False
    except Exception:
        return False
