"""只读解析 Kirikiri TXT 坐标与配方，生成服装和表情组合。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


MAX_CANVAS_SIDE = 20000
MAX_CANVAS_PIXELS = 40_000_000


@dataclass(frozen=True)
class TxtLayer:
    key: str
    name: str
    group: str
    left: int
    top: int
    opacity: int
    layer_id: int
    image_path: Path


@dataclass
class TxtPose:
    label: str
    coordinate_path: Path
    canvas: tuple[int, int]
    layers: dict[str, TxtLayer]
    dresses: dict[str, tuple[str, ...]]
    faces: dict[str, tuple[str, ...]]
    metadata_mode: str


@dataclass(frozen=True)
class TxtBody:
    pose: TxtPose
    dress_name: str


@dataclass
class TxtCharacter:
    name: str
    bodies: dict[str, TxtBody]


TxtLibrary = dict[str, dict[str, TxtCharacter]]


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode("utf-16-le")
    if len(raw) >= 4 and raw[0] == 0 and raw[2] == 0:
        return raw.decode("utf-16-be")
    for encoding in ("cp932", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise UnicodeError(f"无法识别文本编码：{path}")


def coordinate_files(character_dir: Path) -> list[Path]:
    result: list[Path] = []
    for path in character_dir.rglob("*.txt"):
        lower = path.name.lower()
        if lower.endswith("_0.txt") or lower.endswith("_info.txt"):
            continue
        try:
            prefix = read_text(path)[:400]
        except Exception:
            continue
        if "#layer_type" in prefix and "\t" in prefix:
            result.append(path)
    return sorted(result, key=lambda value: str(value).casefold())


def metadata_path(coordinate: Path) -> Path | None:
    info = coordinate.with_name(f"{coordinate.stem}_info.txt")
    if info.exists():
        return info
    sinfo = coordinate.with_suffix(".sinfo")
    return sinfo if sinfo.exists() else None


def parse_coordinates(path: Path) -> tuple[tuple[int, int], dict[str, TxtLayer]]:
    rows = [line.split("\t") for line in read_text(path).splitlines()]
    canvas: tuple[int, int] | None = None
    group_names: dict[str, str] = {}
    for fields in rows:
        if len(fields) >= 6 and not fields[0] and fields[4].isdigit() and fields[5].isdigit():
            canvas = int(fields[4]), int(fields[5])
        if len(fields) >= 10 and fields[0] == "2":
            group_names[fields[9]] = fields[1]
    if canvas is None:
        raise ValueError(f"坐标文件缺少画布尺寸：{path}")

    if not (1 <= canvas[0] <= MAX_CANVAS_SIDE and 1 <= canvas[1] <= MAX_CANVAS_SIDE):
        raise ValueError(
            f"坐标文件的画布尺寸不合理（{canvas[0]}×{canvas[1]}），"
            f"单边不能超过 {MAX_CANVAS_SIDE}px：{path}"
        )
    if canvas[0] * canvas[1] > MAX_CANVAS_PIXELS:
        raise ValueError(
            f"坐标文件的画布太大（{canvas[0]}×{canvas[1]} = {canvas[0] * canvas[1] / 1e6:.1f} 百万像素），"
            f"上限 {MAX_CANVAS_PIXELS / 1e6:.0f} 百万像素：{path}"
        )

    layers: dict[str, TxtLayer] = {}
    for fields in rows:
        if len(fields) < 10 or fields[0] != "0":
            continue
        layer_id = int(fields[9])
        image_path = next(
            (item for item in path.parent.glob(f"{path.stem}_{layer_id}.*") if item.suffix.lower() == ".png"),
            None,
        )
        if image_path is None:
            continue
        group_id = fields[10] if len(fields) > 10 else ""
        group = group_names.get(group_id, "") if group_id else ""
        key = f"{group}/{fields[1]}" if group else fields[1]
        if key in layers:
            continue
        layers[key] = TxtLayer(
            key, fields[1], group, int(fields[2]), int(fields[3]),
            int(fields[7]), layer_id, image_path,
        )
    return canvas, layers


def parse_info(path: Path) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    dress_parts: dict[tuple[str, str], list[str]] = {}
    face_parts: dict[str, list[str]] = {}
    for line in read_text(path).splitlines():
        fields = line.split("\t")
        if len(fields) >= 5 and fields[0] == "dress" and fields[2] == "diff":
            dress_parts.setdefault((fields[1], fields[3]), []).append(fields[4])
        elif len(fields) >= 4 and fields[0] == "face" and fields[2] == "base":
            face_parts.setdefault(fields[1], []).append(fields[3])
    dresses = {f"{label}｜动作{code}": tuple(keys) for (label, code), keys in dress_parts.items()}
    faces = {code: tuple(keys) for code, keys in face_parts.items()}
    return dresses, faces


def _infer_recipes(layers: dict[str, TxtLayer]) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    groups: dict[str, list[TxtLayer]] = {}
    for layer in layers.values():
        groups.setdefault(layer.group, []).append(layer)

    dress_layers: list[TxtLayer] = []
    face_layers: list[TxtLayer] = []
    for group, items in groups.items():
        if re.search(r"服装|服差分|衣装|dress", group, re.IGNORECASE):
            dress_layers.extend(items)
        elif re.search(r"表情|笑顔|その他系|ギャグ系|顔|face", group, re.IGNORECASE):
            face_layers.extend(items)

    ungrouped = [item for item in layers.values() if not item.group]
    if dress_layers:
        dresses = {item.name: (item.key,) for item in dress_layers}
    else:
        #Complete stand-alone layers and base/body layers are both useful
        #fallbacks. Prefer a clearly named base, otherwise the largest PNG.
        candidates = ungrouped or list(layers.values())
        named = [item for item in candidates if re.search(r"ベース|base|素体|本体|制服|服$", item.name, re.IGNORECASE)]
        pool = named or candidates
        base = max(pool, key=lambda item: _image_area(item.image_path))
        dresses = {base.name or "默认服装": (base.key,)}

    faces = {item.name: (item.key,) for item in face_layers}
    if not faces:
        faces = {"默认表情": tuple()}
    return dresses, faces


def _image_area(path: Path) -> int:
    with Image.open(path) as image:
        return image.width * image.height


def build_pose(coordinate: Path, character_dir: Path) -> TxtPose:
    canvas, layers = parse_coordinates(coordinate)
    metadata = metadata_path(coordinate)
    mode = "坐标推断"
    if metadata:
        dresses, faces = parse_info(metadata)
        #Omit recipes that reference images absent from this extraction.
        dresses = {name: keys for name, keys in dresses.items() if keys and all(key in layers for key in keys)}
        faces = {name: keys for name, keys in faces.items() if all(key in layers for key in keys)}
        if dresses:
            mode = "官方配方"
        else:
            dresses, faces = _infer_recipes(layers)
    else:
        dresses, faces = _infer_recipes(layers)
    if not faces:
        faces = {"默认表情": tuple()}
    relative = coordinate.relative_to(character_dir).with_suffix("")
    label = "／".join(relative.parts)
    return TxtPose(label, coordinate, canvas, layers, dresses, faces, mode)


def scan_txt_library(source_root: Path) -> tuple[TxtLibrary, list[str]]:
    library: TxtLibrary = {}
    warnings: list[str] = []
    if not source_root.is_dir():
        return library, warnings
    for game_dir in sorted((item for item in source_root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
        game: dict[str, TxtCharacter] = {}
        for character_dir in sorted((item for item in game_dir.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
            bodies: dict[str, TxtBody] = {}
            for coordinate in coordinate_files(character_dir):
                try:
                    pose = build_pose(coordinate, character_dir)
                    for dress_name in pose.dresses:
                        base_label = f"{pose.label}｜{dress_name}"
                        label = base_label
                        suffix = 2
                        while label in bodies:
                            label = f"{base_label}（{suffix}）"
                            suffix += 1
                        bodies[label] = TxtBody(pose, dress_name)
                except Exception as error:
                    warnings.append(f"{game_dir.name}/{character_dir.name}/{coordinate.name}: {error}")
            if bodies:
                game[character_dir.name] = TxtCharacter(character_dir.name, bodies)
        if game:
            library[game_dir.name] = game
    return library, warnings


class TxtComposer:
    def __init__(self, pose: TxtPose):
        self.pose = pose
        self._images: dict[Path, Image.Image] = {}
        self._weights: dict[Path, int] = {}

    def image(self, path: Path) -> Image.Image:
        if path not in self._images:
            with Image.open(path) as image:
                self._images[path] = image.convert("RGBA")
        return self._images[path]

    def weight(self, layer: TxtLayer) -> int:
        if layer.image_path not in self._weights:
            alpha = self.image(layer.image_path).getchannel("A")
            histogram = alpha.histogram()
            self._weights[layer.image_path] = sum(index * count for index, count in enumerate(histogram))
        return self._weights[layer.image_path] * layer.opacity // 255

    def render(self, keys: Iterable[str]) -> Image.Image:
        specs = [self.pose.layers[key] for key in keys]
        if not specs:
            return Image.new("RGBA", self.pose.canvas, (0, 0, 0, 0))
        specs.sort(key=self.weight, reverse=True)
        canvas = Image.new("RGBA", self.pose.canvas, (0, 0, 0, 0))
        for spec in specs:
            layer = self.image(spec.image_path)
            if spec.opacity != 255:
                layer = layer.copy()
                layer.putalpha(layer.getchannel("A").point(lambda value: value * spec.opacity // 255))
            canvas.alpha_composite(layer, (spec.left, spec.top))
        return canvas


def compose_txt(body: TxtBody, face_name: str) -> Image.Image:
    pose = body.pose
    keys = (*pose.dresses[body.dress_name], *pose.faces[face_name])
    return TxtComposer(pose).render(keys)
