"""PBD 图层投影接口；格式与来源见 文档/PBD格式.md。"""
from dataclasses import dataclass
from pathlib import Path
from pbd_codec import decode_records

MAX_PBD_BYTES = 16 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024

@dataclass(frozen=True)
class PbdLayer:
    layer_id: int
    group_layer_id: int
    name: str
    left: int
    top: int
    width: int
    height: int
    opacity: int
    filename: str

    @property
    def recipe_name(self) -> str:
        return f'[{self.group_layer_id}]{self.name}'

@dataclass(frozen=True)
class PbdDocument:
    width: int
    height: int
    layers: tuple[PbdLayer, ...]

def _integer(record, key, low, high, default=None):
    value = record.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'PBD 字段 {key} 无效')
    return value

def read_pbd(path: Path) -> PbdDocument:
    path = Path(path)
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_PBD_BYTES + 1)
    except OSError as exc:
        raise ValueError(f'无法读取 PBD：{path.name}') from exc
    if len(raw) > MAX_PBD_BYTES:
        raise ValueError('PBD 文件过大')
    records = decode_records(raw, MAX_DECOMPRESSED_BYTES)
    canvases = [record for record in records if 'layer_type' not in record]
    if len(canvases) != 1:
        raise ValueError('PBD 画布数量不支持')
    width = _integer(canvases[0], 'width', 1, 20_000)
    height = _integer(canvases[0], 'height', 1, 20_000)
    if width * height > 100_000_000:
        raise ValueError('PBD 画布过大')
    layers = []
    identifiers = set()
    for record in records:
        if 'layer_type' not in record:
            continue
        kind = _integer(record, 'layer_type', 0, 2)
        if kind == 2:
            continue
        if kind != 0:
            raise ValueError('PBD 图层类型不支持')
        identifier = _integer(record, 'layer_id', 0, 0x7fffffff)
        if identifier in identifiers:
            raise ValueError('PBD 图层编号重复')
        identifiers.add(identifier)
        name = record.get('name')
        if not isinstance(name, str):
            raise ValueError('PBD 图层名称无效')
        layers.append(PbdLayer(
            identifier, _integer(record, 'group_layer_id', -1, 0x7fffffff, -1), name,
            _integer(record, 'left', -20_000, 20_000),
            _integer(record, 'top', -20_000, 20_000),
            _integer(record, 'width', 0, 20_000),
            _integer(record, 'height', 0, 20_000),
            _integer(record, 'opacity', 0, 255), f'{path.stem}_{identifier}.png',
        ))
    if not layers:
        raise ValueError('PBD 没有可用图层')
    return PbdDocument(width, height, tuple(layers))
