"""布局实测：用真实浏览器内核（QtWebEngine）加载本地页面，量"按钮在不在视口内"。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QUrl  #noqa: E402
from PySide6.QtWidgets import QApplication  #noqa: E402

MEASURE_JS = r"""
(function () {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom),
             left: Math.round(r.left), right: Math.round(r.right),
             w: Math.round(r.width), h: Math.round(r.height) };
  };
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    return r.top >= -1 && r.bottom <= window.innerHeight + 1 && r.width > 0 && r.height > 0;
  };
  const ids = ['download', 'save-library', 'open-custom-batch', 'batch-library-quick',
               'game', 'character', 'body', 'face', 'face-browse', 'canvas-viewport'];
  const buttons = {};
  ids.forEach(id => { buttons[id] = { rect: rect(document.getElementById(id)),
                                      inViewport: visible(document.getElementById(id)) }; });
  const doc = document.documentElement;
  // 找"超出页面高度的元素"：这是"按钮看不见"最直接的证据。
  // 不靠截图猜测 —— 截图会因窗口边框/状态栏而截偏，几何不会骗人。
  const overflowing = [];
  document.querySelectorAll('.workspace, .workspace *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.height > 0 && r.bottom > window.innerHeight + 1) {
      overflowing.push((el.id ? '#' + el.id : (el.className.toString().split(' ')[0] || el.tagName)) +
                       '@bottom=' + Math.round(r.bottom));
    }
  });
  return JSON.stringify({
    viewport: { w: window.innerWidth, h: window.innerHeight },
    pageScroll: { scrollH: doc.scrollHeight, clientH: doc.clientHeight,
                  mustScroll: doc.scrollHeight > doc.clientHeight + 1 },
    overflowing: overflowing.slice(0, 12),
    workspace: rect(document.querySelector('.workspace')),
    actionPanel: rect(document.querySelector('.action-panel')),
    actionPanelOverflow: (() => {
      const el = document.querySelector('.action-panel');
      return el ? { scrollH: el.scrollHeight, clientH: el.clientHeight,
                    mustScroll: el.scrollHeight > el.clientHeight + 1 } : null;
    })(),
    canvas: rect(document.getElementById('canvas-viewport')),
    items: buttons,
  }, null, 1);
})()
"""


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:52832"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 720
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()
    view.resize(width, height)
    view.show()
    state = {"done": False, "code": 1}

    def finish(code: int) -> None:
        state["done"] = True
        state["code"] = code
        app.quit()

    def measure() -> None:
        view.page().runJavaScript(MEASURE_JS, on_result)

    def on_result(result) -> None:
        import json

        try:
            data = json.loads(result)
        except Exception as error:
            print("解析测量结果失败：", error, result)
            finish(1)
            return
        print(json.dumps(data, ensure_ascii=False, indent=1))
        problems = []
        if data["pageScroll"]["mustScroll"]:
            problems.append(f"整个页面需要滚动：scrollHeight={data['pageScroll']['scrollH']} "
                            f"> clientHeight={data['pageScroll']['clientH']}")
        for name, info in data["items"].items():
            if info["rect"] is None:
                continue
            if not info["inViewport"]:
                problems.append(f"{name} 不在视口内：{info['rect']}")
        print()
        if problems:
            print("❌ 需要滚动/看不到的东西：")
            for item in problems:
                print("   -", item)
            finish(1)
        else:
            print(f"✅ {width}x{height} 下：页面不需要滚动，主要按钮全部在视口内")
            finish(0)

    def loaded(ok: bool) -> None:

        QTimer.singleShot(6000, measure)

    view.loadFinished.connect(loaded)
    view.load(QUrl(url))
    QTimer.singleShot(30000, lambda: finish(1))
    app.exec()
    return state["code"]


if __name__ == "__main__":
    raise SystemExit(main())
