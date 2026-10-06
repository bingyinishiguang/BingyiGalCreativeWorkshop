"""设置按分组与详情页组织。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ui" / "index.html"

#这些控件 ID 被脚本绑定，调整布局时仍需保留。
LEGACY_CONTROL_IDS = [
    "single-path", "batch-path", "drag-path", "data-dir-path", "pack-import-path",
    "run-diagnostics", "export-diagnostics", "choose-single-path",
    "choose-batch-path", "choose-drag-path", "choose-data-dir", "reset-batch-path",
    "open-batch-path", "reset-drag-path", "open-drag-path", "cleanup-drag-path",
    "reset-data-dir", "open-data-dir", "pack-import-confirm", "pack-import-cancel",
    "pack-import-choose", "rescan-assets", "settings-status",
    "diagnostics-list", "diagnostics-summary", "single-folder-field",
]


def _index_text() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_settings_page_is_a_grouped_list():
    text = _index_text()
    assert 'id="settings-list"' in text, "缺少分组列表根视图"
    assert 'class="settings-group"' in text, "缺少分组"
    assert text.count('data-settings-open="panel-') >= 6, "可点的设置行太少"
    assert 'id="settings-back"' in text, "子页面缺少返回按钮"


def test_every_settings_row_points_at_a_real_panel():
    text = _index_text()
    targets = set(re.findall(r'data-settings-open="([^"]+)"', text))
    assert targets, "没有任何设置行"
    for target in sorted(targets):
        assert f'id="{target}"' in text, f"设置行指向了不存在的子页面：{target}"


def test_settings_legacy_controls_survived_the_redesign():
    text = _index_text()
    missing = [name for name in LEGACY_CONTROL_IDS if f'id="{name}"' not in text]
    assert not missing, f"重做后丢失了这些控件（JS 绑定会静默失效）：{missing}"


def test_settings_summaries_are_inside_detail_panels():
    text = _index_text()
    home = text.split('id="settings-list"',1)[1].split('id="panel-single"',1)[0]
    assert '<small' not in home
    assert 'row-value-' not in home
    assert 'panel-display' not in text
    for name in ("row-value-single", "row-value-batch", "row-value-drag", "row-value-data"):
        assert f'id="{name}"' in text


def test_settings_markup_has_no_script_leftovers():
    text = _index_text()
    assert "_____" not in text, "设置页残留了脚本占位符"
    assert "exports\\Single\\" in text, "单张导出目录提示丢了"


def test_app_js_defines_helpers_before_use():
    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    for name in ("function escapeHtml", "const $ =", "function refreshSettingsRowValues"):
        assert name in app_js, name
    defined_at = app_js.index("function escapeHtml")
    first_use = app_js.find("escapeHtml(")
    assert 0 <= defined_at <= first_use, "escapeHtml 的使用出现在定义之前"


def test_every_called_helper_exists():
    import re

    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    declared = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", app_js))
    declared |= set(re.findall(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=", app_js))
    declared |= set(re.findall(r"\blet\s+([A-Za-z_$][\w$]*)\s*=", app_js))
    #浏览器/环境自带，不参与检查
    builtin = {
        "fetch", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
        "parseInt", "parseFloat", "isNaN", "encodeURIComponent", "decodeURIComponent",
        "alert", "confirm", "Number", "String", "Boolean", "Object", "Array", "JSON",
        "URL", "URLSearchParams", "AbortController", "FormData", "Blob", "File",
        "requestAnimationFrame", "cancelAnimationFrame", "structuredClone", "Promise",
        "Error", "TypeError", "RangeError", "Map", "Set", "Date", "Math", "RegExp",
        "setProperty", "getProperty", "addEventListener", "removeEventListener",
    }
    #检查启动和刷新路径，避免未定义的函数中断界面初始化。
    watched = ["async function bootstrapApp()", "function refreshGames()",
               "function changeGame()", "function changeCharacter()",
               "function syncSettingsFields()", "function showPreview("]
    problems = []
    for header in watched:
        if header not in app_js:
            continue
        body = app_js[app_js.index(header):]
        #取到下一个顶层 function 之前
        next_top = body.find("\nfunction ", len(header))
        if next_top == -1:
            next_top = body.find("\nasync function ", len(header))
        if next_top > 0:
            body = body[:next_top]
        for name in set(re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(", body)):
            if name in declared or name in builtin or name in {"if", "for", "while", "switch", "catch", "return", "function", "typeof", "await", "new"}:
                continue
            problems.append(f"{header} 调用了不存在的 {name}()")
    assert not problems, "；".join(problems)


def test_boot_overlay_is_visible_by_default():
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    line = next(item for item in index.splitlines() if 'id="boot-overlay"' in item)
    assert "hidden" not in line, "加载页必须默认显示（否则会先闪出一个空壳工作台）"

    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "BOOT_SKIP_MS" not in app_js, "旧的「准备快就不显示加载页」逻辑必须删掉"
    assert "loadScanSummary" not in app_js, "死调用必须清除"


def test_empty_state_is_deferred_to_avoid_flash():
    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "EMPTY_STATE_DELAY_MS" in app_js
    assert "function scheduleEmptyState()" in app_js
    assert "function hideEmptyState()" in app_js
    clear_body = app_js[app_js.index("function clearPreview()"):app_js.index("function refreshGames()")]
    assert "scheduleEmptyState()" in clear_body
    assert "empty-state').hidden = false" not in clear_body, "清空时不能立刻显示空态"
    assert "hideEmptyState();" in app_js, "新图到位要取消延迟显示"
    delay = int(app_js.split("EMPTY_STATE_DELAY_MS =")[1].split(";")[0].strip())
    assert 200 <= delay <= 800, delay


def test_import_requires_game_and_character():
    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    for name in ("MISSING_BOTH_TEXT", "MISSING_CHARACTER_TEXT", "MISSING_GAME_TEXT"):
        assert name in app_js, name
    assert "会记不住自己推的是谁吗" in app_js, "校验提示文案缺失"
    assert "你这是在玩我，还是在玩 Galgame" in app_js, "两个都空的文案缺失"
    #四种情况要分别判定（都空 / 缺角色 / 缺作品 / 齐全）
    assert "!gameValue && !characterValue" in app_js, "没区分「两个都空」"

    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="import-game"' in index, "导入弹窗缺少「作品名」输入框"
    assert "required-mark" not in index, "必填标记必须撤掉"
    assert "必须填" not in index, "说明文字必须撤掉"

    #按钮可点击，由提交时的校验提示缺失字段。
    assert "pick.disabled" not in app_js, "导入按钮应允许提交后校验"

    composer = (ROOT / "sprite_composer.py").read_text(encoding="utf-8")
    commit_block = composer[composer.index('if path == "/api/library/import-commit":'):]
    for phrase in ("你这是在玩我，还是在玩 Galgame", "会记不住自己推的是谁吗",
                   "混成一锅"):
        assert phrase in commit_block, f"后端缺少对应文案：{phrase}"
