"""Portable, read-only inference resources and writable voice presets."""
import json
from pathlib import Path
from app_paths import resource_root


def bundle_root():
    return resource_root() / 'tts_bundle'


def resolve(value, base=None):
    value = str(value)
    if value.startswith('@tts/'):
        base = Path(base if base is not None else bundle_root()).resolve()
        result = (base / value[5:]).resolve()
        if not result.is_relative_to(base):
            raise ValueError('配音资源路径不能越过运行目录')
        return str(result)
    return value


def portable(value, base=None):
    try:
        return '@tts/' + Path(value).resolve().relative_to(Path(base if base is not None else bundle_root()).resolve()).as_posix()
    except ValueError:
        return value


def seed_voices(root, base=None):
    for source in (Path(base if base is not None else bundle_root()) / 'voices').glob('*/voice.json'):
        target = Path(root) / source.parent.name / 'voice.json'
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text('utf-8'), encoding='utf-8')


class Component:
    """An optional resource directory, scoped to one user data directory."""
    def __init__(self, state):
        self.state = Path(state)

    def root(self):
        if self.state.is_file():
            try:
                value = json.loads(self.state.read_text('utf-8'))
                selected = value.get('root')
                if selected and Path(selected).is_absolute():
                    return Path(selected)
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            #Explicit disconnect / invalid selection never falls back to bundled resources.
            return self.state.parent / 'component-not-connected'
        return bundle_root()

    @staticmethod
    def inspect(root, verify=False):
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError('配音组件文件夹不存在，请重新选择；历史音频仍可使用')
        manifest = root / 'component.json'
        if manifest.is_file():
            if manifest.stat().st_size > 64000:
                raise ValueError('配音组件清单过大')
            try:
                info = json.loads(manifest.read_text('utf-8-sig'))
            except (ValueError, UnicodeError):
                raise ValueError('配音组件清单无法读取') from None
            if (not isinstance(info, dict) or info.get('schemaVersion') != 1
                    or info.get('componentId') != 'bingyi-gpt-sovits'
                    or info.get('adapter') != 'api_v2'
                    or info.get('serviceRoot') != 'service'
                    or info.get('voicesRoot') != 'voices'
                    or not isinstance(info.get('componentVersion'), str)
                    or not 1 <= len(info['componentVersion']) <= 100):
                raise ValueError('配音组件版本或布局不受支持（需要清单版本 1、api_v2）')
            version = info['componentVersion']
            if 'inventory' in info:
                import hashlib
                inventory=root/'component-files.json'
                if info['inventory']!='component-files.json' or not inventory.is_file() or inventory.stat().st_size>10_000_000:
                    raise ValueError('配音组件文件清单丢失或不受支持')
                raw=inventory.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=info.get('inventorySha256'):
                    raise ValueError('配音组件文件清单校验失败，请保留旧组件并重新下载')
                if verify:
                    try:
                        entries=json.loads(raw)['files']
                        if not isinstance(entries,list) or not 1<=len(entries)<=50000:raise ValueError()
                        for entry in entries:
                            name=entry['path']
                            if not isinstance(name,str) or not name.startswith('service/') or '..' in Path(name).parts:raise ValueError()
                            path=Path(resolve('@tts/'+name,root))
                            if not path.is_file() or path.stat().st_size!=entry['bytes']:
                                raise ValueError('配音组件文件缺失或大小不符：'+name)
                            sha=hashlib.sha256()
                            with path.open('rb') as stream:
                                for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
                            if sha.hexdigest()!=entry['sha256']:raise ValueError('配音组件文件校验失败：'+name)
                    except (KeyError,TypeError,UnicodeError,json.JSONDecodeError):
                        raise ValueError('配音组件文件清单格式不正确') from None
        else:
            #Transitional support for the existing measured CPU resource layout.
            version = '旧版 api_v2 目录（无版本清单）'
        required = ['service/api_v2.py', 'service/runtime/python.exe',
                    'service/GPT_SoVITS/TTS_infer_pack/TTS.py',
                    'service/GPT_SoVITS/pretrained_models/chinese-hubert-base/pytorch_model.bin',
                    'service/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/pytorch_model.bin']
        missing = [name for name in required if not Path(resolve('@tts/' + name, root)).is_file()]
        if not (root / 'voices').is_dir():
            missing.append('voices/')
        if missing:
            raise ValueError('配音组件不完整：' + '、'.join(missing))
        return dict(root=str(root), version=version, adapter='api_v2', legacy=not manifest.is_file())

    def status(self):
        root = self.root()
        if root == self.state.parent/'component-not-connected' or (not self.state.exists() and not root.is_dir()):
            return dict(connected=False, root=str(root), message='尚未连接外置配音组件；历史音频仍可使用')
        try:
            info = self.inspect(root)
            return dict(connected=True, message='已连接配音组件：' + info['version'], **info)
        except (OSError, ValueError) as error:
            return dict(connected=False, root=str(self.root()), message=str(error))

    def select(self, root):
        from rough_cut import atomic_json
        info = self.inspect(root, verify=True)  #Validate before replacing a previous working selection.
        atomic_json(self.state, dict(schemaVersion=1, root=info['root']))
        return info

    def disconnect(self):
        from rough_cut import atomic_json
        atomic_json(self.state, dict(schemaVersion=1, root=None))
