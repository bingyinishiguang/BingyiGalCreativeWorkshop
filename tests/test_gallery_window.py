"""立绘总览「只看收藏」下拉选择框的离屏布局回归测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, QUrl, Slot  #noqa: E402
from PySide6.QtGui import QGuiApplication  #noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  #noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "ui" / "GalleryWindow.qml"


class _PetStub(QObject):
    """替代 Python 侧 pet 桥接：只返回合法 JSON，让 QML 能完成初始化。"""

    def __init__(self):
        super().__init__()
        self.topmost_calls = []
        self.saved = []

    @Slot(result=str)
    def queryGallery(self, *args):
        return '{"items": [], "total": 0, "nextOffset": 0}'

    @Slot(result=str)
    def galleryPosition(self, *args):
        return "{}"

    @Slot(str)
    def setPetTopmost(self, *args):
        return None

    @Slot(bool)
    def setGalleryTopmost(self, topmost):
        self.topmost_calls.append(bool(topmost))

    @Slot(result=str)
    def galleryRect(self, *args):
        return "{}"

    @Slot(int, int, int, int)
    def saveGalleryRect(self, x, y, width, height):
        self.saved.append((int(x), int(y), int(width), int(height)))

    @Slot(str)
    def selectFromGallery(self, *args):
        return None

    @Slot(str)
    def dragCurrent(self, *args):
        return None


@pytest.fixture(scope="module")
def gallery_env():
    """返回 (QML 根对象, pet 桥 stub)，stub 用来断言置顶开关是否被调用。"""
    import desktop_pet

    desktop_pet.apply_qml_style()
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlApplicationEngine()
    stub = _PetStub()
    engine.rootContext().setContextProperty("pet", stub)
    engine.load(QUrl.fromLocalFile(str(QML)))
    roots = engine.rootObjects()
    assert roots, f"GalleryWindow.qml 加载失败：{QML}"
    app.processEvents()
    yield roots[0], stub
    engine.deleteLater()
    app.processEvents()


@pytest.fixture(scope="module")
def gallery_window(gallery_env):
    return gallery_env[0]


def _find(root, name):
    obj = root.findChild(QObject, name)
    assert obj is not None, f"没找到 objectName={name}"
    return obj


def test_qml_loads(gallery_window):
    assert gallery_window is not None
    assert _find(gallery_window, "favoriteFilter") is not None


def test_gallery_is_topmost_by_default(gallery_env):
    root, stub = gallery_env
    flags = int(root.property("flags"))
    assert flags & int(Qt.WindowStaysOnTopHint), "总览窗口没有置顶标志"
    #桥接口本身仍然可用（Python 侧拖拽时用它让位/归位）
    stub.topmost_calls.clear()
    stub.setGalleryTopmost(False)
    stub.setGalleryTopmost(True)
    assert stub.topmost_calls == [False, True]


def test_card_geometry_fits_title_and_detail(gallery_window):
    root = gallery_window
    grid = _find(root, "spriteGrid")
    cell_height = grid.property("cellHeight")

    assert cell_height == root.property("cardCellHeight"), "cellHeight 与常量脱钩了"
    assert cell_height >= root.property("cardContentHeight"), (
        f"卡片高度 {cell_height}px 装不下内容 "
        f"{root.property('cardContentHeight')}px：名称与说明会重叠"
    )
    #必须容得下图 + 名称 + 说明三项之和；同时别撑得过分（避免每屏只看得到一行卡片）
    image_height = root.property("cardImageHeight")
    title_height = root.property("cardTitleHeight")
    detail_height = root.property("cardDetailHeight")
    assert cell_height >= image_height + title_height + detail_height
    assert cell_height <= image_height + title_height + detail_height + 60, "卡片留白过多"


def test_card_geometry_matches_actual_qml_numbers(gallery_window):
    source = QML.read_text(encoding="utf-8")
    root = gallery_window
    assert f"height: {root.property('cardImageHeight')}" in source, "图片区高度常量与 QML 不一致"
    assert f"cellHeight: gallery.cardCellHeight" in source
    assert "anchors.top: cardTitle.bottom" in source, "说明文字必须挂在名称下方，而不是从底部对齐"


def test_category_filters_exist(gallery_window):
    game = _find(gallery_window, "gameFilter")
    character = _find(gallery_window, "characterFilter")
    tags = _find(gallery_window, "favoriteFilter")
    assert game.property("count") >= 1, "作品下拉至少要有『全部作品』"
    assert game.property("displayText") == "全部作品"
    assert character.property("displayText") == "全部角色"
    #标签作为选项并入收藏下拉，但仍必须能按标签筛
    assert tags.property("count") >= 1


def test_tag_and_game_state_drive_queries(gallery_env):
    root, _stub = gallery_env
    assert root.property("activeTag") == ""
    root.setProperty("availableTags", ["开心", "开场"])
    root.setProperty("activeTag", "开心")
    QGuiApplication.processEvents()
    assert root.property("activeTag") == "开心"
    root.setProperty("activeTag", "")
    assert root.property("activeTag") == ""

    source = QML.read_text(encoding="utf-8")
    assert "activeTag === tag" in source, "再点同一个标签应当取消筛选"
    assert "pet.queryGallery(searchInput.text, favoriteOnly, offset," in source, \
        "查询必须把标签/作品一起带给后端"
    assert "activeTag, activeGame" in source


def test_card_has_no_face_badge_or_face_view():
    source = QML.read_text(encoding="utf-8")
    for gone in ('objectName: "faceBadge"', 'objectName: "faceViewImage"',
                 'objectName: "faceViewToggle"', "faceView", "sourceClipRect"):
        assert gone not in source, f"{gone} 应该已经移除"
    assert "spriteFaceUrl" not in source, "卡片模型里不该再传 faceUrl"
    assert "onDoubleClicked" in source, "双击卡片回桌宠模式必须保留"


def test_pet_hides_completely_when_gallery_opens():
    pet_qml = (ROOT / "ui" / "pet.qml").read_text(encoding="utf-8")
    assert "visible: !galleryWindow.visible && !galleryWindow.dragging" in pet_qml, \
        "桌宠显示与否必须由总览状态推导（单一事实来源）"
    assert "? 0.6 : 1" not in pet_qml, "旧的缩到 0.6 倍还在"
    assert "opacity: (galleryWindow.visible" not in pet_qml, "旧的半透明幽灵态还在"


def test_gallery_center_matches_pet_center():
    import desktop_pet

    pet_x, pet_y, pet_w, pet_h = 1400, 600, 240, 345
    gallery_w, gallery_h = 360, 500
    x, y = desktop_pet.gallery_window_position(
        pet_x, pet_y, pet_w, pet_h, gallery_w, gallery_h, 0, 0, 1920, 1040)
    assert x == pet_x + pet_w // 2 - gallery_w // 2, f"中心未对齐，x={x}"
    assert y >= 10 and y + gallery_h <= 1040 - 10, "不能超出工作区"

def test_gallery_size_is_remembered():
    source = QML.read_text(encoding="utf-8")
    assert "onWidthChanged: if (geometryLoaded) geometrySaver.restart()" in source
    assert "onHeightChanged: if (geometryLoaded) geometrySaver.restart()" in source


def test_topmost_is_applied_after_show():
    source = QML.read_text(encoding="utf-8")
    assert "function applyTopmostWithRetry()" in source
    assert "applyTopmostWithRetry()" in source, "显示后必须调用它"
    assert 'id: topmostRetry' in source, "重试要由 Timer 驱动（不是同步连调）"
    assert "pet.setGalleryTopmost(true)" in source
    assert "attempts < 3" in source, "重试必须有上限，否则就是死循环"


def test_pin_button_is_gone_and_drag_auto_yields():
    source = QML.read_text(encoding="utf-8")
    for gone in ("pinButton", "toggleTopmost", "syncPinnedFromSystem",
                 "property bool pinned", "gallery.setTopmost"):
        assert gone not in source, f"图钉开关的残留：{gone}"
    assert "WindowStaysOnTopHint" in source, "平时仍应保持在最上面（创建时带上）"

    pet_py = (ROOT / "desktop_pet.py").read_text(encoding="utf-8")
    drag_body = pet_py[pet_py.index("def dragCurrent(self)"):pet_py.index("def _set_gallery_dragging")]
    assert "self._apply_topmost(gallery_window, False)" in drag_body, "拖拽开始要自动让位"
    assert 'setProperty("visible", False)' in drag_body, \
        "拖拽一开始窗口就该消失"
    assert "_set_gallery_dragging(gallery_window, True)" in drag_body, \
        "必须置位拖拽标志，否则隐藏会触发出桌宠"
    assert "hid_gallery = bool(gallery_window.property(\"visible\"))" in drag_body, \
        "要先判断总览当时是否开着（从桌宠拖时它是关着的）"
    assert "_restore_gallery_topmost" in drag_body, "松手后要自动归位"
    assert "QTimer.singleShot" in drag_body, "归位要延迟一点，别把刚接住文件的剪映盖住"

    restore = pet_py[pet_py.index("def _restore_gallery_topmost"):][:1100]
    assert 'setProperty("visible", True)' in restore, "归位时要把窗口显示回来"
    assert "_apply_topmost(gallery_window, True)" in restore, "归位时恢复置顶"
    assert "if not getattr(self, \"_gallery_hidden_for_drag\", False):" in restore
    assert "return" in restore

    qml = QML.read_text(encoding="utf-8")
    assert "property bool dragging: false" in qml, "缺少拖拽标志"
    assert "if (dragging)" in qml, "拖拽期间不能走「关总览」分支"
    #桌宠的显示只由 pet.qml 的派生绑定负责，这里不该再命令式去藏它
    assert "pet.sinkPetWindow()" not in qml, "总览里不该再命令式藏桌宠（会造成状态错拍）"


def _as_list(value):
    """QML 函数返回的 JS 数组在 Python 侧是 QJSValue，要转成原生 list 才能比较。"""
    if hasattr(value, "toVariant"):
        value = value.toVariant()
    return list(value)


def test_cascading_filter_math_with_real_data(gallery_window):
    root = gallery_window
    root.setProperty("gameCharacters", {
        "常轨脱离": ["妃爱", "华乃"],
        "LimeLightLemonadeJam": ["恵凪", "妃爱"],
        "本地导入": ["A01_自然站姿_微笑"],
    })
    QGuiApplication.processEvents()

    #两个都"全部" → 所有角色都在候选里（去重；顺序按 QML 的默认排序，这里只比集合）
    pool = _as_list(root.characterPool())
    assert set(pool) == {"A01_自然站姿_微笑", "华乃", "恵凪", "妃爱"}, pool
    assert len(pool) == 4, "妃爱同时出现在两部作品里，去重后不能重复"

    #选了作品 → 角色候选只剩这部作品的角色（不会出现别的作品的角色）
    assert _as_list(root.charactersFor("常轨脱离")) == ["妃爱", "华乃"]
    assert _as_list(root.charactersFor("LimeLightLemonadeJam")) == ["恵凪", "妃爱"]
    assert "华乃" not in _as_list(root.charactersFor("LimeLightLemonadeJam"))

    #作品候选 = 全量（选完不能塌成一项，否则换不回去）
    root.setProperty("activeCharacter", "华乃")
    QGuiApplication.processEvents()
    assert _as_list(root.gamesFor("华乃")) == ["常轨脱离"], "华乃只出现在常轨脱离"
    root.setProperty("activeCharacter", "")
    QGuiApplication.processEvents()
    assert _as_list(root.gamesFor("")) == ["LimeLightLemonadeJam", "常轨脱离", "本地导入"], \
        "没选角色时作品候选必须是全量"

    assert "本地导入" in _as_list(root.gamesFor(""))
    assert "A01_自然站姿_微笑" in _as_list(root.characterPool())


def test_cascading_filter_math_with_real_data_cleanup(gallery_window):
    gallery_window.setProperty("gameCharacters", {})
    gallery_window.setProperty("scopedGames", [])
    gallery_window.setProperty("activeCharacter", "")
    QGuiApplication.processEvents()
    source = QML.read_text(encoding="utf-8")
    assert 'objectName: "characterFilter"' in source, "缺少角色下拉"
    assert "gallery.charactersFor(gallery.activeGame)" in source
    assert "gallery.gamesFor(gallery.activeCharacter)" in source
    assert "function syncFilterIndexes()" in source, "候选变化后要把下拉指回当前筛选值"
    assert "activeCharacter" in source and "activeGame" in source
    #查询必须把角色也带上
    assert "activeTag, activeGame, activeCharacter" in source

    assert 'indexOf("姿势:")' in source


def test_long_labels_are_elided(gallery_window):
    source = QML.read_text(encoding="utf-8")
    assert source.count("elide: Text.ElideRight") >= 3, "各下拉标签都要能省略长文本"
    combo = _find(gallery_window, "favoriteFilter")
    assert combo.property("count") >= 2


def test_gallery_geometry_is_remembered(gallery_env):
    _root, stub = gallery_env
    assert json.loads(stub.galleryRect()) == {}, "初始没有存过几何"
    stub.saveGalleryRect(120, 240, 470, 650)
    assert stub.saved == [(120, 240, 470, 650)]


def test_drag_start_threshold_is_sane(gallery_window):
    root = gallery_window
    threshold = root.property("dragStartThreshold")
    assert 4 <= threshold <= 14, f"起拖阈值 {threshold}px 不合理（太小=点击也拖，太大=拖不动）"
    source = QML.read_text(encoding="utf-8")
    assert "gallery.dragStartThreshold" in source, "阈值常量没被实际使用"
    assert "> 20" not in source, "旧的写死 20px 阈值又回来了"


def test_root_respects_minimum_size(gallery_window):
    root = gallery_window
    assert root.property("minimumWidth") >= 280
    assert root.property("minimumHeight") >= 360
    #不能把下限抬到用户的手感值 —— 那样就变成"替他决定大小"了
    assert root.property("minimumWidth") < 461, "下限不应高到限制手感"
    assert root.property("minimumHeight") < 455


def test_filter_dropdown_holds_favorite_and_tags(gallery_window):
    combo = _find(gallery_window, "favoriteFilter")
    assert combo.property("count") >= 2, "至少要有『全部立绘 / 只看收藏』两项"
    assert combo.property("currentIndex") == 0
    assert combo.property("displayText") == "全部立绘"


def test_root_favorite_flag_follows_the_dropdown(gallery_window):
    combo = _find(gallery_window, "favoriteFilter")
    assert gallery_window.property("favoriteOnly") is False

    #模拟用户在下拉里选中「只看收藏」（第 1 项）
    combo.setProperty("currentIndex", 1)
    combo.activated.emit(1)
    assert gallery_window.property("favoriteOnly") is True
    assert combo.property("displayText") == "只看收藏"

    #再选回第 0 项 = 不筛选
    combo.setProperty("currentIndex", 0)
    combo.activated.emit(0)
    assert gallery_window.property("favoriteOnly") is False


def test_filter_label_is_not_clipped(gallery_window):
    combo = _find(gallery_window, "favoriteFilter")
    label = _find(gallery_window, "favoriteFilterLabel")
    arrow = _find(gallery_window, "favoriteFilterArrow")

    #自定义 contentItem 必须自己让出箭头位置，否则文字会被箭头压住或裁掉。
    needed = (label.property("leftPadding")
              + label.property("implicitWidth")
              + label.property("rightPadding"))
    assert combo.property("width") >= needed, (
        f"下拉框太窄：需要 {needed}px，实际 {combo.property('width')}px")
    assert arrow.property("x") >= label.property("leftPadding"), "箭头压到了文字上"


def test_filter_arrow_has_real_size(gallery_window):
    arrow = _find(gallery_window, "favoriteFilterArrow")
    assert arrow.property("implicitWidth") > 0
    assert arrow.property("implicitHeight") > 0


def test_dropdown_popup_has_light_background(gallery_window):
    combo = _find(gallery_window, "favoriteFilter")
    popup = _find(gallery_window, "favoriteFilterPopup")
    bg = _find(gallery_window, "favoriteFilterPopupBg")
    label = _find(gallery_window, "favoriteFilterLabel")

    #把弹层打开，确保拿到的是真实生效的样式而不是未初始化值
    combo.setProperty("currentIndex", 0)
    popup.setProperty("visible", True)
    QGuiApplication.processEvents()

    fill = bg.property("color").name().lower()
    assert fill == "#ffffff", f"下拉弹层底色是 {fill}，应为白色，否则深色字看不清"

    #弹层里的文字用深色（在浅底上可读）
    text_color = label.property("color").name().lower()
    assert text_color not in ("#ffffff", "#f4fbff"), "弹层文字是浅色，在浅底上看不见"

    popup.setProperty("visible", False)

