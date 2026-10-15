"""Readable, collision-safe media packages shared by draft generators."""
import re
import shutil
from pathlib import Path


def readable_name(value):
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')
    # Old library imports sometimes already carry an internal hash.
    label = re.sub(r'[-_](?=[a-fA-F0-9]*[a-fA-F])[a-fA-F0-9]{8,32}$', '', label).strip(' .')
    label = label[:90] or '素材'
    if label.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        label = '素材_' + label
    return label


class MediaPack:
    def __init__(self, staging, final, external=''):
        self.staging = Path(staging)
        self.final = (Path(external) if external else Path(final)).resolve()
        self.external = bool(external)
        if self.external and not self.final.is_dir():
            raise ValueError('素材目录不存在，请先创建并选择素材文件夹')
        self.names = set()
        self.created = []

    def allocate(self, name, suffix):
        label = readable_name(name)
        suffix = suffix.lower()
        candidate = label + suffix
        version = 2
        while candidate.casefold() in self.names or (self.external and (self.final/candidate).exists()):
            candidate = f'{label}_版本{version}{suffix}'
            version += 1
        self.names.add(candidate.casefold())
        return self.staging/candidate

    def copy(self, source, name):
        source = Path(source)
        target = self.allocate(name, source.suffix)
        shutil.copy2(source, target)
        return target

    def path(self, staged):
        return str(self.final/Path(staged).name)

    def publish(self):
        if not self.external:
            return
        try:
            for source in self.staging.iterdir():
                if not source.is_file():
                    continue
                target = self.final/source.name
                # Exclusive creation protects existing edits and concurrent exporters.
                with target.open('xb') as output:
                    self.created.append(target)
                    with source.open('rb') as input_file:
                        shutil.copyfileobj(input_file, output)
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        for path in self.created:
            path.unlink(missing_ok=True)
        self.created.clear()
