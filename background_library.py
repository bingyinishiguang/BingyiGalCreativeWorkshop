"""Local image/video library. Originals are copied, never edited."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}


def media_info(path: Path) -> dict:
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('图片过大，请缩小到四千万像素以内')
            image.load()
            image = ImageOps.exif_transpose(image)
            return dict(kind='image', width=image.width, height=image.height, duration=0)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError('只支持 PNG/JPG/WebP/BMP 图片与 MP4/MOV/MKV/WebM/AVI/M4V 视频')
    try:
        from pymediainfo import MediaInfo
        tracks = MediaInfo.parse(str(path)).video_tracks
        video = tracks[0]
        duration = float(video.duration or 0) / 1000
        if duration <= 0 or not video.width or not video.height:
            raise ValueError('视频没有有效的尺寸或时长')
        return dict(kind='video', width=int(video.width), height=int(video.height), duration=duration)
    except (ImportError, OSError, IndexError) as error:
        raise ValueError('无法读取视频，请检查文件及 pymediainfo 依赖') from error


class BackgroundLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.media = self.root / 'media'
        self.thumbs = self.root / 'thumbs'
        self.media.mkdir(parents=True, exist_ok=True)
        self.thumbs.mkdir(exist_ok=True)
        self.db = self.root / 'backgrounds.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS backgrounds (id TEXT PRIMARY KEY, '
                       'name TEXT NOT NULL, tags TEXT NOT NULL, favorite INTEGER DEFAULT 0, '
                       'filename TEXT NOT NULL, info TEXT NOT NULL, hash TEXT UNIQUE NOT NULL, '
                       'deleted INTEGER DEFAULT 0)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def item(self, row):
        if row is None:
            raise ValueError('背景不存在或已移入回收站')
        result = dict(row)
        result.update(json.loads(result.pop('info')))
        result['tags'] = json.loads(result['tags'])
        result['favorite'] = bool(result['favorite'])
        result['missing'] = not (self.media / result['filename']).is_file()
        result['thumbnail'] = (self.thumbs / (result['id'] + '.jpg')).is_file()
        return result

    def get(self, item_id, deleted=False):
        with self.connect() as db:
            return self.item(db.execute('SELECT * FROM backgrounds WHERE id=? AND deleted=?',
                                       (str(item_id), int(deleted))).fetchone())

    def file(self, item_id):
        item = self.get(item_id)
        path = self.media / item['filename']
        if not path.is_file():
            raise ValueError('背景文件丢失，请重新导入原文件')
        return path

    def list(self, search='', kind='', favorite=False, trash=False):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM backgrounds WHERE deleted=? ORDER BY favorite DESC, rowid DESC',
                              (int(trash),)).fetchall()
        items = [self.item(row) for row in rows]
        query = str(search).casefold()
        items = [i for i in items if (not query or query in (i['name'] + ' ' + ' '.join(i['tags'])).casefold())
                 and (not kind or i['kind'] == kind) and (not favorite or i['favorite'])]
        return {'items': items, 'total': len(items)}

    def import_file(self, source: Path, tags=()):
        source = Path(source).resolve()
        if not source.is_file() or source.is_symlink():
            raise ValueError('素材文件不存在')
        info = media_info(source)
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        content_hash = digest.hexdigest()
        with self.connect() as db:
            previous = db.execute('SELECT * FROM backgrounds WHERE hash=?', (content_hash,)).fetchone()
            if previous:
                dest = self.media / previous['filename']
                if not dest.is_file():
                    self._copy(source, dest, info['kind'])
                db.execute('UPDATE backgrounds SET deleted=0 WHERE id=?', (previous['id'],))
                restored = dict(previous)
                restored['deleted'] = 0
                return {'duplicate': True, 'item': self.item(restored)}
        item_id = uuid.uuid4().hex
        filename = item_id + source.suffix.lower()
        dest = self.media / filename
        #Normalize orientation for preview/export agreement; keep the original untouched.
        if info['kind'] == 'image':
            filename = item_id + '.png'
            dest = self.media / filename
            self._copy(source, dest, info['kind'])
        else:
            shutil.copy2(source, dest)
        self._thumbnail(item_id, dest, info['kind'])
        try:
            with self.connect() as db:
                db.execute('INSERT INTO backgrounds(id,name,tags,filename,info,hash) VALUES (?,?,?,?,?,?)',
                           (item_id, source.stem[:200], json.dumps(self.tags(tags)), filename,
                            json.dumps(info), content_hash))
        except sqlite3.IntegrityError:
            dest.unlink(missing_ok=True)
            (self.thumbs / (item_id + '.jpg')).unlink(missing_ok=True)
            with self.connect() as db:
                previous = db.execute('SELECT * FROM backgrounds WHERE hash=?', (content_hash,)).fetchone()
            return {'duplicate': True, 'item': self.item(previous)}
        return {'duplicate': False, 'item': self.get(item_id)}

    @staticmethod
    def _copy(source, dest, kind):
        if kind == 'image':
            with Image.open(source) as image:
                ImageOps.exif_transpose(image).convert('RGBA').save(dest, 'PNG')
        else:
            shutil.copy2(source, dest)

    @staticmethod
    def tags(values):
        if isinstance(values, str):
            values = values.replace('，', ',').split(',')
        if not isinstance(values, (list, tuple)):
            raise ValueError('标签格式不正确')
        return list(dict.fromkeys(str(v).strip()[:50] for v in values if str(v).strip()))[:30]

    def update(self, item_id, name, tags, favorite):
        self.get(item_id)
        name = str(name).strip()[:200]
        if not name:
            raise ValueError('请输入背景名称')
        with self.connect() as db:
            db.execute('UPDATE backgrounds SET name=?,tags=?,favorite=? WHERE id=?',
                       (name, json.dumps(self.tags(tags)), int(favorite is True), str(item_id)))
        return self.get(item_id)

    def trash(self, item_id, restore=False):
        self.get(item_id, deleted=restore)
        with self.connect() as db:
            db.execute('UPDATE backgrounds SET deleted=? WHERE id=?', (0 if restore else 1, str(item_id)))
        return {'ok': True}

    def _thumbnail(self, item_id, path, kind):
        target = self.thumbs / (item_id + '.jpg')
        if kind == 'image':
            with Image.open(path) as image:
                image = image.convert('RGB')
                image.thumbnail((400, 240))
                image.save(target, quality=85)
        elif shutil.which('ffmpeg'):
            try:
                subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(path), '-frames:v', '1',
                                '-vf', 'scale=400:240:force_original_aspect_ratio=decrease', '-y', str(target)],
                               capture_output=True, timeout=20, creationflags=0x08000000 if os.name == 'nt' else 0)
            except (OSError, subprocess.TimeoutExpired):
                pass  #Video remains usable with the video placeholder.
