from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from sprite_library import SpriteLibrary
import app_paths
from windows_file_drag import (DroppedOnForbiddenTarget, cleanup_drag_copy, drag_file,
                               make_draggable_copy, set_drag_dir, sprite_filename)


BACKGROUND = "#eef4fa"
SURFACE = "#ffffff"
TEXT = "#263e5a"
MUTED = "#748ba5"
BLUE = "#3d83d3"
LIGHT_BLUE = "#eaf4ff"
BORDER = "#d8e6f2"

#增量加载每页条数：一次只查询并解码一小批，滚动到底部再取下一页。
PAGE_SIZE = 60


def query_page(library: SpriteLibrary, search: str, favorite: bool, offset: int,
               limit: int = PAGE_SIZE) -> dict:
    """查询普通分区的一页立绘（含总数），供取用窗增量加载使用。"""
    return library.list(False, search=search.strip()[:100], favorite=favorite,
                        limit=limit, offset=offset)


def query_library_items(library: SpriteLibrary, search: str = "", favorites: bool = False) -> list[dict]:
    """一次性读取普通分区全部立绘（保留给测试与简单调用方使用，不再 200 封顶）。"""
    return library.list(False, search=search.strip()[:100], favorite=favorites,
                        limit=1_000_000)["items"]


class FloatingPicker:
    def __init__(self, root: tk.Tk, library: SpriteLibrary):
        self.root = root
        self.library = library
        self.items: list[dict] = []
        self.total = 0
        self.loading = False
        self.selected: dict | None = None
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self._buttons: dict[str, tk.Button] = {}
        self._placeholder: ImageTk.PhotoImage | None = None
        self._rendered = 0
        self._generation = 0
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.search_after: str | None = None
        self.drag_origin: tuple[int, int] | None = None
        self.drag_started = False
        self.collapsed = False

        #后台解码：工作线程只做 PIL 解码，结果放入线程安全队列，
        #主线程通过 root.after 轮询回填 PhotoImage，避免跨线程操作 tkinter。
        self._decode_queue: queue.Queue = queue.Queue()
        self._ready_queue: queue.Queue = queue.Queue()
        self._pending_decodes = 0
        self._polling = False
        self._decode_worker = threading.Thread(
            target=self._decode_loop, name="picker-decode", daemon=True,
        )
        self._decode_worker.start()

        self.root.title("冰翼立绘取用窗")
        self.root.configure(bg=BACKGROUND)
        self.root.attributes("-topmost", True)
        self.root.minsize(330, 74)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._place_top_right(390, 760)

        self.header = tk.Frame(root, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        self.header.pack(fill="x")
        tk.Label(self.header, text="冰翼立绘取用窗", bg=SURFACE, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=(14, 8), pady=12)
        self.hide_button = tk.Button(self.header, text="隐藏", command=self.root.iconify, **self._flat_button())
        self.hide_button.pack(side="right", padx=(3, 10), pady=8)
        self.collapse_button = tk.Button(self.header, text="收起", command=self.toggle_collapsed, **self._flat_button())
        self.collapse_button.pack(side="right", padx=3, pady=8)

        self.content = tk.Frame(root, bg=BACKGROUND)
        self.content.pack(fill="both", expand=True)

        tools = tk.Frame(self.content, bg=BACKGROUND)
        tools.pack(fill="x", padx=12, pady=(12, 8))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(tools, textvariable=self.search_var, relief="flat", bg=SURFACE,
                                     fg=TEXT, insertbackground=TEXT, font=("Microsoft YaHei UI", 10),
                                     highlightbackground=BORDER, highlightcolor=BLUE, highlightthickness=1)
        self.search_entry.pack(fill="x", ipady=9)
        self.search_entry.insert(0, "")
        self.search_entry.bind("<KeyRelease>", self.schedule_refresh)

        filter_row = tk.Frame(self.content, bg=BACKGROUND)
        filter_row.pack(fill="x", padx=12, pady=(0, 8))
        self.favorite_var = tk.BooleanVar(value=False)
        tk.Checkbutton(filter_row, text="只看收藏", variable=self.favorite_var, command=self.refresh,
                       bg=BACKGROUND, fg=TEXT, activebackground=BACKGROUND, activeforeground=TEXT,
                       selectcolor=SURFACE, font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Button(filter_row, text="刷新图库", command=self.refresh, **self._flat_button()).pack(side="right")

        self.preview_card = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        self.preview_card.pack(fill="x", padx=12, pady=(0, 10))
        self.preview_label = tk.Label(self.preview_card, text="选择一张立绘", bg=SURFACE, fg=MUTED,
                                      height=13, cursor="hand2", font=("Microsoft YaHei UI", 9))
        self.preview_label.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.preview_label.bind("<ButtonPress-1>", self.on_drag_press)
        self.preview_label.bind("<B1-Motion>", self.on_drag_motion)
        self.preview_name = tk.Label(self.preview_card, text="", bg=SURFACE, fg=TEXT,
                                     font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
        self.preview_name.pack(fill="x", padx=10)
        self.preview_meta = tk.Label(self.preview_card, text="", bg=SURFACE, fg=MUTED,
                                     font=("Microsoft YaHei UI", 8), anchor="w")
        self.preview_meta.pack(fill="x", padx=10, pady=(2, 8))

        list_card = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        list_card.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.canvas = tk.Canvas(list_card, bg=SURFACE, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_card, orient="vertical", command=self._on_scroll)
        self.grid = tk.Frame(self.canvas, bg=SURFACE)
        self.grid_window = self.canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.grid.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.grid_window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        self.status = tk.Label(self.content, text="按住图片，拖到剪映素材区", bg=BACKGROUND, fg=MUTED,
                               font=("Microsoft YaHei UI", 8), anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 10))

        self.refresh()

    @staticmethod
    def _flat_button() -> dict:
        return {
            "relief": "flat", "bd": 0, "bg": "#f4f8fd", "fg": "#4b759f",
            "activebackground": LIGHT_BLUE, "activeforeground": BLUE,
            "font": ("Microsoft YaHei UI", 8, "bold"), "padx": 8, "pady": 5,
        }

    def _place_top_right(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        actual_height = min(height, max(420, screen_height - 90))
        self.root.geometry(f"{width}x{actual_height}+{max(8, screen_width - width - 22)}+28")

    def schedule_refresh(self, _event=None) -> None:
        if self.search_after:
            self.root.after_cancel(self.search_after)
        self.search_after = self.root.after(180, self.refresh)

    def refresh(self) -> None:
        self.search_after = None
        self.clear_grid()
        self.items = []
        self.total = 0
        self.load_more_page()

    def load_more_page(self) -> None:
        """加载下一页立绘并增量渲染；避免重复进入和越界。"""
        if self.loading:
            return
        if self.total and len(self.items) >= self.total:
            return
        self.loading = True
        try:
            page = query_page(self.library, self.search_var.get(),
                              self.favorite_var.get(), len(self.items))
            self.total = page["total"]
            new_items = page["items"]
            self.items.extend(new_items)
            self.append_items(new_items)
            if not self._rendered:
                self.show_empty()
            elif self.selected is None:
                self.select_first_visible()
            self.status.configure(
                text=f"普通立绘 · 已载入 {len(self.items)} / {self.total} 张 · 拖动图片即可发送文件",
                fg=MUTED,
            )
            self.root.after(60, self._fill_viewport)
        except Exception as error:
            self.status.configure(text=f"读取立绘库失败：{error}", fg="#a94b50")
        finally:
            self.loading = False

    def clear_grid(self) -> None:
        """清空网格与待回填状态；旧解码结果靠 generation 失效。"""
        self._generation += 1
        for child in self.grid.winfo_children():
            child.destroy()
        self.photos.clear()
        self._buttons.clear()
        self._rendered = 0
        for column in range(3):
            self.grid.grid_columnconfigure(column, weight=1, uniform="sprite")

    def append_items(self, items: list[dict]) -> None:
        """为新增立绘创建占位按钮，并把解码任务交给后台线程。"""
        if self._placeholder is None:
            self._placeholder = ImageTk.PhotoImage(
                Image.new("RGB", (100, 135), "#f0f5fa")
            )
        for item in items:
            if item["missing"]:
                continue
            path = self.library.file(item["id"], False)
            if path is None:
                continue
            name = item["displayName"] or item["character"]
            if item["favorite"]:
                name = "★ " + name
            button = tk.Button(
                self.grid, image=self._placeholder,
                text=f"{name}\n{item['face']}", compound="top",
                command=lambda value=item: self.select_item(value), cursor="hand2",
                relief="flat", bd=0, bg="#f8fbff", fg=TEXT, activebackground=LIGHT_BLUE,
                activeforeground=BLUE, font=("Microsoft YaHei UI", 8), padx=4, pady=5,
                wraplength=104, anchor="n",
            )
            button.grid(row=self._rendered // 3, column=self._rendered % 3,
                        sticky="nsew", padx=3, pady=3)
            button.drag_item = item
            button.bind("<ButtonPress-1>", self.on_drag_press, add="+")
            button.bind("<B1-Motion>", self.on_drag_motion, add="+")
            self._buttons[item["id"]] = button
            self._rendered += 1
            self._schedule_decode(item["id"], path, (100, 135))

    def show_empty(self) -> None:
        message = "没有匹配的立绘" if (self.search_var.get() or self.favorite_var.get()) else "立绘库还是空的"
        tk.Label(self.grid, text=message, bg=SURFACE, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).grid(row=0, column=0, columnspan=3, pady=40)
        self.clear_preview()

    def select_first_visible(self) -> None:
        for item in self.items:
            if item["id"] in self._buttons:
                self.select_item(item)
                return

    def _schedule_decode(self, item_id: str, path: Path, size: tuple[int, int]) -> None:
        self._pending_decodes += 1
        self._decode_queue.put((self._generation, item_id, path, size))
        if not self._polling:
            self._polling = True
            self.root.after(40, self._poll_decode)

    def _decode_loop(self) -> None:
        """后台线程：只做纯 PIL 解码，结果经队列交回主线程。"""
        while True:
            task = self._decode_queue.get()
            if task is None:
                return
            generation, item_id, path, size = task
            try:
                image = self.compose_image(path, size)
            except Exception:
                image = None
            self._ready_queue.put((generation, item_id, image))

    def _poll_decode(self) -> None:
        """主线程轮询回填已解码的缩略图。"""
        self._polling = False
        while True:
            try:
                generation, item_id, image = self._ready_queue.get_nowait()
            except queue.Empty:
                break
            self._pending_decodes -= 1
            if generation == self._generation:
                self._apply_thumb(item_id, image)
        if self._pending_decodes > 0:
            self._polling = True
            self.root.after(40, self._poll_decode)

    def _apply_thumb(self, item_id: str, image: Image.Image | None) -> None:
        button = self._buttons.get(item_id)
        if button is None or image is None:
            return
        photo = ImageTk.PhotoImage(image)
        self.photos[item_id] = photo
        button.configure(image=photo)

    def _on_scroll(self, *args) -> None:
        self.canvas.yview(*args)
        self.root.after(0, self._maybe_load_more)

    def _maybe_load_more(self) -> None:
        if self.loading or not self.total or len(self.items) >= self.total:
            return
        first, last = self.canvas.yview()
        if last >= 0.95:
            self.load_more_page()

    def _fill_viewport(self) -> None:
        """首屏内容不足一屏时自动补载，确保滚动条可用。"""
        if self.loading or not self.total or len(self.items) >= self.total:
            return
        self.canvas.update_idletasks()
        region = self.canvas.bbox("all")
        if region is None:
            return
        if region[3] <= self.canvas.winfo_height() + 40:
            self.load_more_page()

    def close(self) -> None:
        self._decode_queue.put(None)
        self.root.destroy()

    def select_item(self, item: dict) -> None:
        path = self.library.file(item["id"], False)
        if path is None:
            self.status.configure(text="图片文件已丢失，请在主图库中处理", fg="#a94b50")
            return
        self.selected = item
        self.preview_photo = self.make_photo(path, (330, 300))
        self.preview_label.configure(image=self.preview_photo, text="")
        self.preview_label.drag_item = item
        self.preview_name.configure(text=item["displayName"] or f"{item['character']} / {item['face']}")
        tags = " · ".join(item["tags"])
        meta = f"{item['game']} · {item['body']} / {item['face']}"
        self.preview_meta.configure(text=meta + (f" · {tags}" if tags else ""))

    def clear_preview(self) -> None:
        self.selected = None
        self.preview_photo = None
        self.preview_label.configure(image="", text="选择一张立绘")
        self.preview_name.configure(text="")
        self.preview_meta.configure(text="")

    @staticmethod
    def compose_image(path: Path, size: tuple[int, int]) -> Image.Image:
        """纯 PIL 解码 + 缩略 + 棋盘底，供主线程/后台线程复用。"""
        with Image.open(path) as source:
            image = source.convert("RGBA")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        backdrop = Image.new("RGBA", size, "#edf3f8")
        draw = ImageDraw.Draw(backdrop)
        cell = 12
        for y in range(0, size[1], cell):
            for x in range(0, size[0], cell):
                if (x // cell + y // cell) % 2:
                    draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#e2ebf3")
        left = (size[0] - image.width) // 2
        top = (size[1] - image.height) // 2
        backdrop.alpha_composite(image, (left, top))
        return backdrop.convert("RGB")

    @staticmethod
    def make_photo(path: Path, size: tuple[int, int]) -> ImageTk.PhotoImage:
        return ImageTk.PhotoImage(FloatingPicker.compose_image(path, size))

    def on_drag_press(self, event) -> None:
        self.drag_origin = (event.x_root, event.y_root)
        self.drag_started = False

    def on_drag_motion(self, event) -> None:
        if self.drag_started or self.drag_origin is None:
            return
        if abs(event.x_root - self.drag_origin[0]) + abs(event.y_root - self.drag_origin[1]) < 20:
            return
        item = getattr(event.widget, "drag_item", None) or self.selected
        if item is None:
            return
        path = self.library.file(item["id"], False)
        if path is None:
            self.status.configure(text="无法拖动：图片文件已丢失", fg="#a94b50")
            return
        self.drag_started = True
        self.status.configure(text=f"正在拖动：{item['displayName'] or item['character']}…", fg=MUTED)
        self.root.update_idletasks()
        target = None
        dropped = False
        try:
            #复制为带语义名的 PNG（角色_标签_表情.png），剪映素材区直接可读；
            target = make_draggable_copy(path, sprite_filename(item))
            dropped = drag_file(target)
            self.status.configure(
                text="已拖到剪映/PR（文件保留在 DragOut，工程随时可读）" if dropped else "已取消拖动",
                fg="#3d7b58" if dropped else MUTED,
            )
        except DroppedOnForbiddenTarget:
            self.status.configure(text="已取消：不能拖到桌面或文件夹，请拖到剪映素材区", fg=MUTED)
        except Exception as error:
            self.status.configure(text=f"拖动失败：{error}", fg="#a94b50")
        finally:
            cleanup_drag_copy(target, dropped)
            self.drag_origin = None

    def on_mousewheel(self, event) -> None:
        if self.root.winfo_containing(event.x_root, event.y_root) in self._descendants(self.grid):
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
            self.root.after(0, self._maybe_load_more)

    @staticmethod
    def _descendants(widget: tk.Widget) -> set[tk.Widget]:
        result = {widget}
        for child in widget.winfo_children():
            result.update(FloatingPicker._descendants(child))
        return result

    def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.content.pack_forget()
            self.collapse_button.configure(text="展开")
            self._place_top_right(330, 74)
        else:
            self.content.pack(fill="both", expand=True)
            self.collapse_button.configure(text="收起")
            self._place_top_right(390, 760)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冰翼Gal创作工坊悬浮取用窗口技术原型。")
    parser.add_argument("--library-root", type=Path, help="测试用立绘库目录。")
    arguments = parser.parse_args(argv)
    code_dir = Path(__file__).resolve().parent
    library_root = (arguments.library_root or app_paths.resolve_data_dir() / "exports" / app_paths.LIBRARY_DIR_NAME).resolve()
    #不再用 %TEMP%，也不会在拖出后自动删除（剪映/PR 按路径引用素材）。
    try:
        from app_settings import AppSettings

        set_drag_dir(AppSettings(app_paths.resolve_data_dir()).drag_directory())
    except Exception:
        set_drag_dir(None)
    library = SpriteLibrary(library_root)
    root = tk.Tk()
    FloatingPicker(root, library)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
