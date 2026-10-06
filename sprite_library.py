from __future__ import annotations

import hashlib
import json
import io
import os
import random
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from PIL import Image, PngImagePlugin

import app_paths


def _log_library_issue(message: str) -> None:
    """记录图库故障；启动日志不可用时回退到 stderr。"""
    try:
        log_path = app_paths.resolve_data_dir() / "startup.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[library {stamp}] {message}\n")
    except Exception:
        try:
            print(f"[library] {message}", flush=True)
        except Exception:
            pass

#限制导入格式、大小和像素量；透明度只用于区分立绘与背景图。
IMPORT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".ape"})
IMPORT_MIN_SIDE = 32
IMPORT_MAX_SIDE = 8192
#解码和 RGBA 转换会同时占用内存，限制像素总量以控制导入峰值。
IMPORT_MAX_PIXELS = 12_000_000
IMPORT_MIN_BYTES = 1024
IMPORT_MAX_BYTES = 50 * 1024 * 1024

#校验文件头，避免把改过扩展名的音频或其他文件当作图片。
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_BMP = b"BM"
_AUDIO_MAGIC = (b"ID3", b"fLaC", b"OggS", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
_RIFF = b"RIFF"

#四角透明阈值与边缘透明占比阈值（alpha 0-255）
_CORNER_ALPHA_MAX = 16
_EDGE_TRANSPARENT_OK = 0.30
_EDGE_TRANSPARENT_REJECT = 0.05
_OVERALL_TRANSPARENT_REJECT = 0.02

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_REJECT = "reject"


def _looks_transparent_sprite(rgba: Image.Image) -> tuple[str, str, dict]:
    """根据四角、边缘与整体透明度区分立绘、背景图和贴边警告。"""
    width, height = rgba.size
    alpha = rgba.getchannel("A")
    pixels = alpha.load()

    corners = [
        pixels[0, 0], pixels[width - 1, 0],
        pixels[0, height - 1], pixels[width - 1, height - 1],
    ]
    corners_opaque = all(value > _CORNER_ALPHA_MAX for value in corners)

    #沿四边采样，统计透明像素占比
    transparent = 0
    total = 0
    for x in range(width):
        for y in (0, height - 1):
            total += 1
            if pixels[x, y] <= _CORNER_ALPHA_MAX:
                transparent += 1
    for y in range(height):
        for x in (0, width - 1):
            total += 1
            if pixels[x, y] <= _CORNER_ALPHA_MAX:
                transparent += 1
    edge_ratio = transparent / total if total else 0.0

    #用直方图统计透明占比，避免在 Python 中逐像素遍历。
    histogram = alpha.histogram()
    transparent_all = sum(histogram[:_CORNER_ALPHA_MAX + 1])
    overall_ratio = transparent_all / (width * height) if width and height else 0.0

    metrics = {
        "corners": corners,
        "cornersOpaque": corners_opaque,
        "edgeTransparentRatio": round(edge_ratio, 4),
        "overallTransparentRatio": round(overall_ratio, 4),
    }

    if corners_opaque or edge_ratio < _EDGE_TRANSPARENT_REJECT:
        return LEVEL_REJECT, "四周不透明，像是带背景的图或截图（不是透明立绘）", metrics
    if overall_ratio < _OVERALL_TRANSPARENT_REJECT:
        return LEVEL_REJECT, "几乎没有透明区域，判定为矩形背景图", metrics
    if edge_ratio < _EDGE_TRANSPARENT_OK:
        return LEVEL_WARN, "透明区域偏少（可能是贴边立绘或背景没抠干净），请确认后再导入", metrics
    return LEVEL_OK, "看起来是透明立绘", metrics


def validate_import_candidate(path: Path) -> dict:
    """只读校验扩展名、文件头、解码、像素上限与透明度，返回逐张结果。"""
    result: dict = {"path": str(path), "name": path.name, "level": LEVEL_REJECT,
                    "reason": "", "image": None, "width": 0, "height": 0, "format": ""}
    suffix = path.suffix.lower()

    #校验扩展名。
    if suffix in AUDIO_EXTENSIONS:
        result["reason"] = f"这是音频文件（{suffix.lstrip('.').upper()}），不是立绘图片，已拒绝"
        return result
    if suffix not in IMPORT_EXTENSIONS:
        result["reason"] = f"不支持的格式「{suffix or '无扩展名'}」，只接受 PNG / JPG / WEBP / BMP，已拒绝"
        return result

    #先检查文件大小，避免读入过大的内容。
    try:
        size = path.stat().st_size
    except OSError as error:
        result["reason"] = f"读不到这个文件：{error}"
        return result
    if size < IMPORT_MIN_BYTES:
        result["reason"] = f"文件太小（{size} 字节），不像是立绘图片"
        return result
    if size > IMPORT_MAX_BYTES:
        result["reason"] = f"文件太大（{size / 1048576:.1f} MB），超过 50 MB 上限"
        return result

    #文件头匹配后再解码，拒绝损坏图片。
    try:
        head = path.open("rb").read(16)
    except OSError as error:
        result["reason"] = f"读不到这个文件：{error}"
        return result
    if head.startswith(_AUDIO_MAGIC) or (head.startswith(_RIFF) and head[8:12] == b"WAVE"):
        result["reason"] = "文件内容是音频，只是被改名成了图片，已拒绝"
        return result
    if not (head.startswith(_MAGIC_PNG) or head.startswith(_MAGIC_JPEG)
            or head.startswith(_MAGIC_BMP) or (head.startswith(_RIFF) and head[8:12] == b"WEBP")):
        result["reason"] = "文件头不像图片（可能被改名或已损坏），已拒绝"
        return result

    try:
        with Image.open(path) as opened:
            result["format"] = (opened.format or "").upper()
            opened.load()
            width, height = opened.size
            #BMP/JPG 等无 alpha 通道的格式，天生就是「矩形背景图」
            has_alpha = opened.mode in ("RGBA", "LA", "PA") or "transparency" in opened.info
            rgba = opened.convert("RGBA")
    except Image.DecompressionBombError:
        result["reason"] = "图片尺寸异常巨大（可能被恶意构造），已拒绝"
        return result
    except Exception as error:
        result["reason"] = f"这张图打不开或已损坏（{type(error).__name__}），已拒绝"
        return result

    result["width"], result["height"] = width, height

    #限制单边尺寸和像素总量。
    if min(width, height) < IMPORT_MIN_SIDE:
        result["reason"] = f"尺寸太小（{width}×{height}），立绘至少要有 {IMPORT_MIN_SIDE}px"
        return result
    if max(width, height) > IMPORT_MAX_SIDE:
        result["reason"] = f"尺寸太大（{width}×{height}），任一边不能超过 {IMPORT_MAX_SIDE}px"
        return result
    if width * height > IMPORT_MAX_PIXELS:
        result["reason"] = f"像素总量太大（{width * height / 1e6:.1f} 百万），超过 {IMPORT_MAX_PIXELS / 10_000:g} 万上限"
        return result

    #根据透明度区分立绘、背景图和可确认的警告。
    if not has_alpha:
        result["reason"] = f"{result['format'] or suffix.lstrip('.').upper()} 天生没有透明通道，属于矩形背景图，已拒绝"
        return result

    level, reason, metrics = _looks_transparent_sprite(rgba)
    result.update({"level": level, "reason": reason, "metrics": metrics, "image": rgba})
    return result


class SpriteLibrary:
    def __init__(self, root: Path):
        self.root = root
        self.images = root / "images"
        self.trash = root / "trash"
        self.thumbs = root / "thumbs"
        self._migrate_legacy_layout()
        self.root.mkdir(parents=True, exist_ok=True)
        self.images.mkdir(parents=True, exist_ok=True)
        self.trash.mkdir(parents=True, exist_ok=True)
        self.thumbs.mkdir(parents=True, exist_ok=True)
        try:
            self._initialize_schema()
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as error:
            #隔离损坏数据库后重建；保留原始图片和坏库供恢复。
            backup = self._quarantine_broken_database(error)
            _log_library_issue(
                f"立绘库数据库无法使用（{error}），已改名为 {backup.name} 并重建空库。"
                f"立绘图片文件都在 {self.images} 下，未受影响；元数据可从该备份里人工恢复。"
            )
            self._initialize_schema()

    def _quarantine_broken_database(self, error: Exception) -> Path:
        """把不可用的库文件改名为 .broken-<时间戳>（含 -wal/-shm），返回主文件新路径。"""
        database = self.root / app_paths.LIBRARY_DB_NAME
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = database.with_name(f"{database.name}.broken-{stamp}")
        for suffix in ("", "-wal", "-shm"):
            source = database.with_name(database.name + suffix)
            if not source.exists():
                continue
            destination = backup if suffix == "" else backup.with_name(backup.name + suffix)
            try:
                os.replace(source, destination)
            except OSError:
                #改不动（只读盘等）就删掉，否则下面重建还是会失败。
                try:
                    source.unlink()
                except OSError:
                    pass
        return backup

    def _initialize_schema(self) -> None:
        """建表 / 补列 / 建索引 / 回填哈希。可从 `__init__` 里重试一次。"""
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sprites (
                    id TEXT PRIMARY KEY,
                    game TEXT NOT NULL,
                    character TEXT NOT NULL,
                    body TEXT NOT NULL,
                    face TEXT NOT NULL,
                    category TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    saved_at TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    deleted_at TEXT NOT NULL DEFAULT ''
                )
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(sprites)")}
            additions = {
                "display_name": "TEXT NOT NULL DEFAULT ''",
                "note": "TEXT NOT NULL DEFAULT ''",
                "favorite": "INTEGER NOT NULL DEFAULT 0",
                "content_hash": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "deleted_at": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE sprites ADD COLUMN {name} {definition}")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sprite_tags (
                    sprite_id TEXT NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (sprite_id, tag_id),
                    FOREIGN KEY (sprite_id) REFERENCES sprites(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS sprites_category_saved ON sprites(category, saved_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS sprites_game_character ON sprites(game, character)")
            connection.execute("CREATE INDEX IF NOT EXISTS sprites_deleted ON sprites(deleted_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS sprites_hash ON sprites(content_hash)")
            #唯一索引约束未删除的图片；旧库存在重复时跳过建索引并记录日志。
            try:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS sprites_unique_live "
                    "ON sprites(game, character, body, face, category, content_hash) "
                    "WHERE deleted_at = ''"
                )
            except sqlite3.IntegrityError:
                duplicates = connection.execute(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT game, character, body, face, category, content_hash"
                    "  FROM sprites WHERE deleted_at = ''"
                    "  GROUP BY game, character, body, face, category, content_hash HAVING COUNT(*) > 1"
                    ")"
                ).fetchone()[0]
                _log_library_issue(
                    f"库里存在 {duplicates} 组未删除的重复立绘，唯一索引未能建立（去重仍由应用层负责）。"
                    f"如需彻底清理：在立绘库里删掉重复的那几张，或删除 {self.root} 下的库文件重建（会丢标签/备注）。"
                )
            connection.execute("CREATE INDEX IF NOT EXISTS sprite_tags_tag ON sprite_tags(tag_id, sprite_id)")
            connection.execute("UPDATE sprites SET updated_at = saved_at WHERE updated_at = ''")
            unhashed = connection.execute(
                "SELECT id, relative_path FROM sprites WHERE content_hash = ''"
            ).fetchall()
            skipped = 0
            for row in unhashed:
                path = (self.root / row["relative_path"]).resolve()
                if path.is_relative_to(self.images.resolve()) and path.is_file():
                    with Image.open(path) as image:
                        digest = self._image_hash(image)
                    #哈希冲突只跳过当前条目，不能触发整库隔离。
                    try:
                        with connection:
                            connection.execute("UPDATE sprites SET content_hash = ? WHERE id = ?",
                                               (digest, row["id"]))
                    except sqlite3.IntegrityError:
                        skipped += 1
            if skipped:
                _log_library_issue(
                    f"有 {skipped} 条立绘的历史内容哈希与库里已有记录重复，已跳过回填"
                    f"（这些记录仍可正常使用，只是不参与内容去重）。"
                )

    #迁移目录时同步改写数据库相对路径，保留旧目录。
    LEGACY_DIR_RENAMES = {"图片": "images", "缩略图": "thumbs", "回收站": "trash"}
    LEGACY_DB_NAMES = ("立绘库.sqlite3",)

    def _migrate_legacy_layout(self) -> int:
        """迁移旧目录时同步改写数据库相对路径，并保留旧目录以便恢复。"""
        renamed = 0
        try:
            for old_name, new_name in self.LEGACY_DIR_RENAMES.items():
                old_dir = self.root / old_name
                new_dir = self.root / new_name
                if not old_dir.is_dir():
                    continue
                new_dir.mkdir(parents=True, exist_ok=True)
                for child in old_dir.iterdir():
                    target = new_dir / child.name
                    if target.exists():
                        continue
                    os.replace(child, target)
                    renamed += 1
            for legacy_db in self.LEGACY_DB_NAMES:
                old_db = self.root / legacy_db
                new_db = self.root / app_paths.LIBRARY_DB_NAME
                if old_db.is_file() and not new_db.exists():
                    os.replace(old_db, new_db)
                for suffix in ("-wal", "-shm"):
                    old_side = self.root / f"{legacy_db}{suffix}"
                    new_side = self.root / f"{app_paths.LIBRARY_DB_NAME}{suffix}"
                    if old_side.is_file() and not new_side.exists():
                        os.replace(old_side, new_side)

            db = self.root / app_paths.LIBRARY_DB_NAME
            if not db.is_file():
                return renamed
            connection = sqlite3.connect(db, timeout=15)
            try:
                connection.row_factory = sqlite3.Row
                tables = {row["name"] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
                if "sprites" not in tables:
                    return renamed
                with connection:
                    for old_name, new_name in self.LEGACY_DIR_RENAMES.items():
                        cursor = connection.execute(
                            "UPDATE sprites SET relative_path = ? || substr(relative_path, ?) "
                            "WHERE relative_path LIKE ?",
                            (new_name, len(old_name) + 1, f"{old_name}/%"),
                        )
                        renamed += cursor.rowcount or 0
            finally:
                connection.close()
        except Exception:
            pass
        return renamed

    @contextmanager
    def _connect(self):
        """创建独立 SQLite 连接，设置锁等待；WAL 不可用时降级记录。"""
    @contextmanager
    def _connect(self):
        """创建独立 SQLite 连接，设置锁等待；WAL 不可用时降级记录。"""
        connection = sqlite3.connect(self.root / app_paths.LIBRARY_DB_NAME, timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            #WAL 不可用时记录日志，不阻止图库访问。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError as error:
                _log_library_issue(f"无法启用 WAL 日志模式（将按默认模式运行）：{error}")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _collect_orphans(self, minimum_age_seconds: float = 900.0) -> dict:
        """只报告无数据库记录且超过年龄阈值的文件，避免误判正在写入的内容。"""
        with self._connect() as connection:
            known_ids = {row["id"] for row in connection.execute("SELECT id FROM sprites")}
        cutoff = time.time() - max(0.0, minimum_age_seconds)
        orphans: dict[str, list[Path]] = {"images": [], "thumbs": []}
        for folder, key in ((self.images, "images"), (self.thumbs, "thumbs")):
            if not folder.is_dir():
                continue
            for path in folder.rglob("*"):
                if not path.is_file():
                    continue
                #按图片 ID 识别缓存；.head.png 等多重后缀不能只用 Path.stem。
                stem = path.stem
                if stem.endswith(".head"):
                    stem = stem[: -len(".head")]
                if stem in known_ids:
                    continue
                try:
                    if path.stat().st_mtime > cutoff:
                        continue  #太新：可能是正在写入的那一张
                except OSError:
                    continue
                orphans[key].append(path)
        return orphans

    def delete_orphans(self, paths: list[Path]) -> int:
        """删除已确认的孤儿文件；再次检查路径位于图库目录内。"""
        allowed = [self.images.resolve(), self.thumbs.resolve()]
        removed = 0
        for path in paths:
            try:
                resolved = Path(path).resolve()
            except OSError:
                continue
            if not any(resolved.is_relative_to(root) for root in allowed):
                continue
            try:
                resolved.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    @staticmethod
    def _image_hash(image: Image.Image) -> str:
        rgba = image.convert("RGBA")
        rgba.thumbnail((256, 256), Image.Resampling.LANCZOS)
        digest = hashlib.sha256()
        digest.update(f"RGBA:{rgba.width}x{rgba.height}:".encode("ascii"))
        digest.update(rgba.tobytes())
        return digest.hexdigest()

    @staticmethod
    def _valid_id(item_id: object) -> bool:
        return (isinstance(item_id, str) and len(item_id) == 32
                and all(letter in "0123456789abcdef" for letter in item_id))

    @staticmethod
    def _mode_matches(category: str, special: bool) -> bool:
        return (category != "normal") == special

    def _active_path(self, relative_path: str) -> Path | None:
        path = (self.root / relative_path).resolve()
        return path if path.is_relative_to(self.images.resolve()) else None

    def _trash_path(self, item_id: str) -> Path:
        return self.trash / f"{item_id}.png"

    @staticmethod
    def _normalize_tags(tags: object) -> list[str]:
        """接受标签列表或逗号分隔文本；忽略大小写去重，限制数量与长度。"""
        if isinstance(tags, str):
            tags = [part for part in re.split(r"[,，]", tags)]
        if not isinstance(tags, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in tags:
            if not isinstance(value, str):
                continue
            name = value.strip()[:30]
            key = name.casefold()
            if name and key not in seen:
                result.append(name)
                seen.add(key)
            if len(result) == 20:
                break
        return result

    @staticmethod
    def _escape_like(value: str) -> str:
        return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def _tags_for(self, connection: sqlite3.Connection, item_id: str) -> list[str]:
        return [row["name"] for row in connection.execute(
            "SELECT tags.name FROM tags JOIN sprite_tags ON tags.id = sprite_tags.tag_id "
            "WHERE sprite_tags.sprite_id = ? ORDER BY tags.name COLLATE NOCASE",
            (item_id,),
        )]

    def _tags_for_many(self, connection: sqlite3.Connection, item_ids: list[str]) -> dict[str, list[str]]:
        if not item_ids:
            return {}
        placeholders = ",".join("?" for _ in item_ids)
        rows = connection.execute(
            "SELECT sprite_tags.sprite_id, tags.name FROM tags "
            "JOIN sprite_tags ON tags.id = sprite_tags.tag_id "
            f"WHERE sprite_tags.sprite_id IN ({placeholders}) ORDER BY tags.name COLLATE NOCASE",
            item_ids,
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["sprite_id"], []).append(row["name"])
        return result

    def _item(self, connection: sqlite3.Connection, row: sqlite3.Row,
              tags: list[str] | None = None) -> dict:
        deleted = bool(row["deleted_at"])
        path = self._trash_path(row["id"]) if deleted else self._active_path(row["relative_path"])
        source_geometry = None
        if path and path.is_file():
            try:
                with Image.open(path) as image:
                    raw_geometry = image.info.get('bingyi_geometry')
                    source_geometry = json.loads(raw_geometry) if raw_geometry else None
            except (OSError, ValueError):
                pass
        return {
            "id": row["id"], "game": row["game"], "character": row["character"],
            "sourceGeometry": source_geometry,
            "body": row["body"], "face": row["face"], "category": row["category"],
            "width": row["width"], "height": row["height"], "savedAt": row["saved_at"],
            "updatedAt": row["updated_at"], "deletedAt": row["deleted_at"],
            "displayName": row["display_name"], "note": row["note"],
            "favorite": bool(row["favorite"]),
            "tags": self._tags_for(connection, row["id"]) if tags is None else tags,
            "missing": path is None or not path.is_file(),
        }

    def _find(self, connection: sqlite3.Connection, item_id: object, special: bool,
              deleted: bool | None = None) -> sqlite3.Row | None:
        if not self._valid_id(item_id):
            return None
        row = connection.execute("SELECT * FROM sprites WHERE id = ?", (item_id,)).fetchone()
        if row is None or not self._mode_matches(row["category"], special):
            return None
        if deleted is not None and bool(row["deleted_at"]) != deleted:
            return None
        return row

    def save(self, game: str, character: str, body: str, face: str, category: str,
             image: Image.Image, tags: object = None) -> dict:
        """保存立绘并查重；命中已有图片时合并新标签。"""
        rgba = image.convert("RGBA")
        png_meta = PngImagePlugin.PngInfo()
        geometry = image.info.get('bingyi_geometry')
        if geometry:
            png_meta.add_text('bingyi_geometry', geometry)
        content_hash = self._image_hash(rgba)
        new_tags = self._normalize_tags(tags)
        with self._connect() as connection:
            duplicate = connection.execute(
                "SELECT * FROM sprites WHERE game = ? AND character = ? AND body = ? AND face = ? "
                "AND category = ? AND content_hash = ? AND deleted_at = '' ORDER BY saved_at DESC LIMIT 1",
                (game, character, body, face, category, content_hash),
            ).fetchone()
            if duplicate is not None:
                destination = self._active_path(duplicate["relative_path"])
                repaired = destination is not None and not destination.is_file()
                if repaired or geometry:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(destination.name+"."+uuid.uuid4().hex+".tmp")
                    rgba.save(temporary, format="PNG", pnginfo=png_meta)
                    os.replace(temporary, destination)
                merged_tags = new_tags
                if new_tags:
                    merged_tags = self._merge_tags_atomically(connection, duplicate["id"], new_tags)
                item = self._item(connection, duplicate, merged_tags)
                item.update({"path": str(destination) if destination else "", "created": False,
                             "duplicate": True, "repaired": repaired})
                return item

        item_id = uuid.uuid4().hex
        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        directory = self.images / item_id[:2]
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{item_id}.png"
        temporary = directory / f"{item_id}.tmp"
        relative_path = destination.relative_to(self.root).as_posix()
        try:
            rgba.save(temporary, format="PNG", pnginfo=png_meta)
            os.replace(temporary, destination)
            self._write_thumbnail(item_id, rgba)
            with self._connect() as connection:
                try:
                    connection.execute("""
                        INSERT INTO sprites (
                            id, game, character, body, face, category, relative_path, width, height,
                            saved_at, content_hash, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (item_id, game, character, body, face, category, relative_path,
                          rgba.width, rgba.height, saved_at, content_hash, saved_at))
                except sqlite3.IntegrityError:
                    #并发请求可能在查重后插入相同图片，由唯一索引保证不重复入库。
                    connection.rollback()
                    duplicate_row = connection.execute(
                        "SELECT * FROM sprites WHERE game = ? AND character = ? AND body = ? "
                        "AND face = ? AND category = ? AND content_hash = ? AND deleted_at = '' "
                        "ORDER BY saved_at DESC LIMIT 1",
                        (game, character, body, face, category, content_hash),
                    ).fetchone()
                    if duplicate_row is None:
                        raise
                    temporary.unlink(missing_ok=True)
                    destination.unlink(missing_ok=True)
                    merged_fallback = new_tags
                    if new_tags:
                        merged_fallback = self._merge_tags_atomically(
                            connection, duplicate_row["id"], new_tags)
                    existing = self._item(connection, duplicate_row, merged_fallback)
                    existing.update({"path": str(self._active_path(duplicate_row["relative_path"]) or ""),
                                     "created": False, "duplicate": True, "repaired": False})
                    return existing
                row = connection.execute("SELECT * FROM sprites WHERE id = ?", (item_id,)).fetchone()
                if new_tags:
                    self._set_tags(connection, item_id, new_tags)
                item = self._item(connection, row, new_tags)
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        item.update({"path": str(destination), "created": True, "duplicate": False, "repaired": False})
        return item

    def find_by_content_hash(self, digest: str) -> dict | None:
        """按内容哈希查找已入库图片，避免重复保存。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sprites WHERE content_hash = ? AND deleted_at = '' LIMIT 1",
                (digest,),
            ).fetchone()
            return self._item(connection, row) if row is not None else None

    def import_image(self, path: Path, character: str, tags: object = None,
                     force: bool = False, game: str = "") -> dict:
        """校验本地图片并入库；force 仅覆盖透明度警告，不绕过格式与解码校验。"""
        outcome = validate_import_candidate(path)
        resolved_character = (character or "").strip()[:100] or "未命名"
        resolved_game = (game or "").strip()[:60] or "本地导入"
        base = {
            "name": path.name,
            "character": resolved_character,
            "game": resolved_game,
            "reason": outcome["reason"],
            "width": outcome.get("width", 0),
            "height": outcome.get("height", 0),
            "metrics": outcome.get("metrics", {}),
        }

        hard_reject = outcome["level"] == LEVEL_REJECT
        #强制导入只覆盖透明度警告，格式错误、损坏和超限仍然拒绝。
        forceable = bool(outcome.get("metrics"))
        if hard_reject and not (force and forceable):
            return {**base, "status": "rejected"}
        if outcome["level"] == LEVEL_WARN and not force:
            return {**base, "status": "warning"}

        image = outcome.get("image")
        if image is None:
            return {**base, "status": "rejected", "reason": outcome["reason"] or "无法读取这张图片"}

        digest = self._image_hash(image)
        existing = self.find_by_content_hash(digest)
        if existing is not None:
            #重复命中时合并标签，保留已有元数据。
            normalized = self._normalize_tags(tags)
            if normalized:
                updated = self.update(existing["id"], False, existing.get("displayName") or "",
                                      existing.get("note") or "", existing.get("favorite") or False,
                                      [*(existing.get("tags") or []), *normalized])
                if updated is not None:
                    existing = updated
            return {**base, "status": "duplicate", "id": existing["id"], "item": existing,
                    "reason": "库里已经有这张图了（内容完全相同），没有重复保存；"
                              + ("已把这次填的标签合并进去" if normalized else "标签也没变")}

        item = self.save(resolved_game, resolved_character, "manual", path.stem, "normal", image,
                         self._normalize_tags(tags))
        return {**base, "status": "imported", "id": item["id"], "item": item}

    def list(self, special: bool, search: str = "", game: str = "", character: str = "",
             tag: str = "", favorite: bool = False, trash: bool = False,
             limit: int = 48, offset: int = 0) -> dict:
        where = ["sprites.category <> 'normal'" if special else "sprites.category = 'normal'",
                 "sprites.deleted_at <> ''" if trash else "sprites.deleted_at = ''"]
        args: list[object] = []
        if game:
            where.append("sprites.game = ?")
            args.append(game)
        if character:
            where.append("sprites.character = ?")
            args.append(character)
        if favorite:
            where.append("sprites.favorite = 1")
        if tag:
            where.append("EXISTS (SELECT 1 FROM sprite_tags st JOIN tags t ON t.id = st.tag_id "
                         "WHERE st.sprite_id = sprites.id AND t.name = ? COLLATE NOCASE)")
            args.append(tag)
        if search:
            where.append("(sprites.game LIKE ? ESCAPE '\\' OR sprites.character LIKE ? ESCAPE '\\' "
                         "OR sprites.body LIKE ? ESCAPE '\\' OR sprites.face LIKE ? ESCAPE '\\' "
                         "OR sprites.display_name LIKE ? ESCAPE '\\' OR sprites.note LIKE ? ESCAPE '\\' "
                         "OR EXISTS (SELECT 1 FROM sprite_tags ss JOIN tags tt ON tt.id = ss.tag_id "
                         "WHERE ss.sprite_id = sprites.id AND tt.name LIKE ? ESCAPE '\\'))")
            pattern = self._escape_like(search)
            args.extend([pattern] * 7)
        clause = " AND ".join(where)
        with self._connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM sprites WHERE {clause}", args).fetchone()[0]
            rows = connection.execute(
                f"SELECT sprites.* FROM sprites WHERE {clause} "
                f"ORDER BY sprites.favorite DESC, "
                f"{'sprites.deleted_at DESC' if trash else 'sprites.updated_at DESC'}, sprites.id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            available_tags = [row["name"] for row in connection.execute(
                "SELECT DISTINCT tags.name FROM tags JOIN sprite_tags ON tags.id = sprite_tags.tag_id "
                "JOIN sprites ON sprites.id = sprite_tags.sprite_id WHERE "
                + ("sprites.category <> 'normal'" if special else "sprites.category = 'normal'")
                + " AND " + ("sprites.deleted_at <> ''" if trash else "sprites.deleted_at = ''")
                + " ORDER BY tags.name COLLATE NOCASE"
            )]
            scope = ("sprites.category <> 'normal'" if special else "sprites.category = 'normal'") \
                + " AND " + ("sprites.deleted_at <> ''" if trash else "sprites.deleted_at = ''")
            #作品与角色筛选相互约束。
            game_clause = " AND sprites.game = ?" if game else ""
            game_args: list[object] = [game] if game else []
            character_clause = " AND sprites.character = ?" if character else ""
            character_args: list[object] = [character] if character else []
            available_games = [row[0] for row in connection.execute(
                f"SELECT DISTINCT sprites.game FROM sprites WHERE {scope} "
                "ORDER BY sprites.game COLLATE NOCASE")]
            available_characters = [row[0] for row in connection.execute(
                f"SELECT DISTINCT sprites.character FROM sprites WHERE {scope}{game_clause} "
                "ORDER BY sprites.character COLLATE NOCASE", game_args)]
            scoped_games = [row[0] for row in connection.execute(
                f"SELECT DISTINCT sprites.game FROM sprites WHERE {scope}{character_clause} "
                "ORDER BY sprites.game COLLATE NOCASE", character_args)]
            #级联筛选使用完整对应表，避免当前结果限制下一次筛选。
            game_characters: dict[str, list[str]] = {}
            for row in connection.execute(
                    f"SELECT DISTINCT sprites.game, sprites.character FROM sprites WHERE {scope} "
                    "ORDER BY sprites.game COLLATE NOCASE, sprites.character COLLATE NOCASE"):
                game_characters.setdefault(row[0], []).append(row[1])
            ids = [row["id"] for row in rows]
            tags_map = self._tags_for_many(connection, ids)
            items = [self._item(connection, row, tags_map.get(row["id"], [])) for row in rows]
        return {"items": items, "total": total, "tags": available_tags,
                "games": available_games, "characters": available_characters,
                "scopedGames": scoped_games, "gameCharacters": game_characters}

    def _set_tags(self, connection: sqlite3.Connection, item_id: str, tags: list[str]) -> None:
        """整份替换某个立绘的标签（与 update() 同一口径：清空孤儿标签）。"""
        connection.execute("DELETE FROM sprite_tags WHERE sprite_id = ?", (item_id,))
        for tag_name in tags:
            connection.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (tag_name,))
            tag_id = connection.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
            connection.execute("INSERT INTO sprite_tags(sprite_id, tag_id) VALUES (?, ?)", (item_id, tag_id))
        connection.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM sprite_tags WHERE tag_id = tags.id)")

    def _merge_tags_atomically(self, connection: sqlite3.Connection, item_id: str,
                               new_tags: list[str]) -> list[str]:
        """以 BEGIN IMMEDIATE 串行执行标签的读取、合并与写回，锁竞争时退避重试。"""
        last_error: Exception | None = None
        for _ in range(5):
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                last_error = error
                time.sleep(random.uniform(0.01, 0.06))
                continue
            try:
                existing = self._tags_for(connection, item_id)
                merged = self._normalize_tags([*existing, *new_tags])
                self._set_tags(connection, item_id, merged)
                connection.commit()
                return merged
            except Exception:
                connection.rollback()
                raise
        if last_error is not None:
            raise last_error
        return self._normalize_tags(new_tags)

    def metadata(self, item_id: object, special: bool = False) -> dict | None:
        """Read current metadata without exposing database internals to exporters."""
        with self._connect() as connection:
            row = self._find(connection,item_id,special,deleted=False)
            return self._item(connection,row) if row is not None else None

    def update(self, item_id: object, special: bool, display_name: object, note: object,
               favorite: object, tags: object = ...) -> dict | None:
        """更新元数据；未传 tags 时保留，传空列表时清空，无效类型不修改。"""
        name = display_name.strip()[:100] if isinstance(display_name, str) else ""
        memo = note.strip()[:1000] if isinstance(note, str) else ""
        replace_tags = isinstance(tags, list)
        normalized_tags = self._normalize_tags(tags) if replace_tags else []
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connect() as connection:
            row = self._find(connection, item_id, special, deleted=False)
            if row is None:
                return None
            connection.execute(
                "UPDATE sprites SET display_name = ?, note = ?, favorite = ?, updated_at = ? WHERE id = ?",
                (name, memo, 1 if favorite else 0, updated_at, item_id),
            )
            if replace_tags:
                self._set_tags(connection, item_id, normalized_tags)
            updated = connection.execute("SELECT * FROM sprites WHERE id = ?", (item_id,)).fetchone()
            return self._item(connection, updated)

    def move_to_trash(self, item_id: object, special: bool) -> dict | None:
        with self._connect() as connection:
            row = self._find(connection, item_id, special, deleted=False)
            if row is None:
                return None
            source = self._active_path(row["relative_path"])
            destination = self._trash_path(row["id"])
            was_missing = source is None or not source.is_file()
            if not was_missing:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise FileExistsError("回收站中已经存在同名文件")
                os.replace(source, destination)
            #回收站列表仍然要显示这些立绘的缩略图，删掉缓存后 `thumbnail_bytes()`
            deleted_at = datetime.now().astimezone().isoformat(timespec="seconds")
            connection.execute("UPDATE sprites SET deleted_at = ?, updated_at = ? WHERE id = ?",
                               (deleted_at, deleted_at, item_id))
            changed = connection.execute("SELECT * FROM sprites WHERE id = ?", (item_id,)).fetchone()
            item = self._item(connection, changed)
            item["wasMissing"] = was_missing
            return item

    def restore(self, item_id: object, special: bool) -> dict | None:
        with self._connect() as connection:
            row = self._find(connection, item_id, special, deleted=True)
            if row is None:
                return None
            duplicate = connection.execute(
                "SELECT id FROM sprites WHERE id <> ? AND game = ? AND character = ? AND body = ? "
                "AND face = ? AND category = ? AND content_hash = ? AND deleted_at = '' LIMIT 1",
                (item_id, row["game"], row["character"], row["body"], row["face"],
                 row["category"], row["content_hash"]),
            ).fetchone()
            if duplicate is not None:
                raise FileExistsError("图库中已经有相同立绘，请先处理现有图片")
            source = self._trash_path(row["id"])
            destination = self._active_path(row["relative_path"])
            if destination is None or not source.is_file():
                raise FileNotFoundError("回收站中的立绘文件不存在")
            if destination.exists():
                raise FileExistsError("原位置已经存在同名文件")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            connection.execute("UPDATE sprites SET deleted_at = '', updated_at = ? WHERE id = ?",
                               (updated_at, item_id))
            changed = connection.execute("SELECT * FROM sprites WHERE id = ?", (item_id,)).fetchone()
            return self._item(connection, changed)

    def delete_permanently(self, item_id: object, special: bool) -> bool:
        with self._connect() as connection:
            row = self._find(connection, item_id, special, deleted=True)
            if row is None:
                return False
            trash_file = self._trash_path(row["id"])
            if trash_file.exists():
                trash_file.unlink()
            self._drop_thumbnail(item_id)
            connection.execute("DELETE FROM sprite_tags WHERE sprite_id = ?", (item_id,))
            connection.execute("DELETE FROM sprites WHERE id = ?", (item_id,))
            connection.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM sprite_tags WHERE tag_id = tags.id)")
            return True

    def file(self, item_id: str, special: bool, include_deleted: bool = False) -> Path | None:
        with self._connect() as connection:
            row = self._find(connection, item_id, special, deleted=include_deleted)
        if row is None:
            return None
        path = self._trash_path(row["id"]) if include_deleted else self._active_path(row["relative_path"])
        if path is None or not path.is_file():
            return None
        return path

    def thumbnail_path(self, item_id: str) -> Path:
        return self.thumbs / f"{item_id}.webp"

    def _drop_thumbnail(self, item_id: str) -> None:
        """同时清理普通缩略图、头部特写与临时缓存。"""
        for suffix in (".webp", ".tmp", ".head.png", ".head.tmp"):
            try:
                (self.thumbs / f"{item_id}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass

    def _write_thumbnail(self, item_id: str, image: Image.Image) -> None:
        """尽力而为地生成 ≤256 的 WebP 缩略图；失败静默忽略，不影响主流程。"""
        try:
            resized = image.convert("RGBA")
            resized.thumbnail((256, 256), Image.Resampling.LANCZOS)
            temporary = self.thumbs / f"{item_id}.tmp"
            resized.save(temporary, format="WEBP")
            os.replace(temporary, self.thumbnail_path(item_id))
        except Exception:
            pass

    def head_bytes(self, item_id: str, special: bool = False, trash: bool = False,
                   head_ratio: float = 0.42) -> bytes | None:
        """从原图裁取顶部区域并缩放到 256 像素内，避免放大缩略图损失细节。"""
        if not self._valid_id(item_id):
            return None
        path = self.file(item_id, special, trash)
        if path is None:
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except Exception:
            return None
        width, height = image.size
        if width <= 0 or height <= 0:
            return None
        #只取顶部一段（头 + 肩）。比例夹在合理区间，防止异常图片算出 0 高。
        ratio = min(0.9, max(0.15, float(head_ratio)))
        head_height = max(1, min(height, int(round(height * ratio))))
        head = image.crop((0, 0, width, head_height))
        #放大到 256 以内：小图不放大（避免糊），大图缩小到刚好。
        head.thumbnail((256, 256), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        try:
            head.save(stream, format="PNG")
        except Exception:
            return None
        return stream.getvalue()

    def head_path(self, item_id: str, special: bool = False, trash: bool = False) -> Path | None:
        """校验图片访问权限后返回或生成 .head.png 缓存，供 QML 文件加载使用。"""
        if not self._valid_id(item_id):
            return None
        #先确认这条立绘确实存在且落在要求的分区里，再考虑用缓存。
        if self.file(item_id, special, trash) is None:
            return None
        cached = self.thumbs / f"{item_id}.head.png"
        try:
            if cached.is_file() and cached.stat().st_size > 0:
                return cached
        except OSError:
            pass
        data = self.head_bytes(item_id, special, trash)
        if data is None:
            return None
        try:
            self.thumbs.mkdir(parents=True, exist_ok=True)
            temporary = self.thumbs / f"{item_id}.head.tmp"
            temporary.write_bytes(data)
            os.replace(temporary, cached)
        except OSError:
            return None
        return cached

    def thumbnail_bytes(self, item_id: str, special: bool = False,
                        trash: bool = False) -> bytes | None:
        """校验类别与回收站状态后返回缩略图；缺失时生成不超过 256 像素的 WebP。"""
        if not self._valid_id(item_id):
            return None
        #先按分区/回收站状态确认这条记录确实属于当前模式（原图接口同一口径）。
        if self.file(item_id, special, trash) is None:
            return None
        thumb = self.thumbnail_path(item_id)
        try:
            if thumb.is_file():
                return thumb.read_bytes()
        except OSError:
            return None
        path = self.file(item_id, special, trash)
        if path is None:
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except Exception:
            return None
        self._write_thumbnail(item_id, image)
        try:
            return thumb.read_bytes() if thumb.is_file() else None
        except OSError:
            return None
