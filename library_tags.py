"""按作品、角色和批量导入标记生成图库标签。"""
from __future__ import annotations

MAX_AUTO_TAGS = 18


def build_auto_tags(item: dict, *, batch_label: str = "", source: str = "批量入库",
                    with_face: bool = True, with_body: bool = True) -> list[str]:
    """按已有元数据生成一组标签（顺序稳定、去重、不含空值）。"""
    tags: list[str] = []

    def add(value: object, prefix: str = "") -> None:
        if not isinstance(value, str):
            return
        name = value.strip()
        if not name:
            return
        tags.append(f"{prefix}{name}" if prefix else name)

    add(item.get("game"), "作品:")
    add(item.get("character"), "角色:")
    if with_body:
        add(item.get("body"), "姿势:")
    if with_face:
        add(item.get("face"), "表情:")

    category = item.get("category") or "normal"
    add("分区:普通" if category == "normal" else "分区:特殊")
    if item.get("favorite") is True:
        add("收藏")
    add(batch_label)
    add(source)

    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = tag.casefold()
        if key in seen:
            continue
        result.append(tag)
        seen.add(key)
        if len(result) >= MAX_AUTO_TAGS:
            break
    return result
