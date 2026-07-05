"""
Trickcal Revive 即时翻译覆盖层 v1.5
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ocr_pipeline import KoreanOcrPipeline, roi_is_paragraph
from screen_capture import capture_game_window_roi
from game_string_db import get_game_string_db
from ko_zh_db import get_ko_zh_db
from translator_backends import (
    contains_hangul,
    resolve_ui_ko_label,
    translate_glossary_from_pool,
    translate_ui_label,
    _compact_ko,
)

try:
    import win32gui
except ImportError:
    win32gui = None

TRANSPARENT_COLOR = "#ff00ff"
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

CACHE_PATH = Path(__file__).with_name("translation_cache.json")
CONFIG_PATH = Path(__file__).with_name("user_config.json")

# 标题含这些子串的窗口不参与匹配（避免误选 IDE / 浏览器等）
EXCLUDE_TITLE_KEYWORDS = (
    "cursor",
    "visual studio code",
    "vscode",
    "文件资源管理器",
    "explorer",
    "microsoft edge",
    "chrome",
    "firefox",
    "bilibili",
    "哔哩哔哩",
    "program manager",
    "nvidia geforce overlay",
    "windows 输入",
    "设置",
    "overlay_translator",
)

# 关键字优先级加分（越大越优先）
PREFER_TITLE_KEYWORDS = (
    "trickcal",
    "aivm-x",
    "aivm_x",
    "异世界",
    "恶作剧",
)


@dataclass
class AppConfig:
    window_keyword: str = "trickcal"
    poll_interval: float = 5.0
    overlay_alpha: float = 0.92
    use_cache: bool = True
    translate_engine: str = "bing"
    subtitle_boost: bool = True
    fast_mode: bool = True
    coverage_boost: bool = True
    max_overlay_regions: int = 40



class TranslationCache:
    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, str] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def get(self, text: str) -> Optional[str]:
        key = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()
        return self._data.get(key)

    def set(self, src: str, dst: str) -> None:
        key = hashlib.sha1(src.strip().encode("utf-8")).hexdigest()
        self._data[key] = dst

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


def load_user_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _title_excluded(title: str) -> bool:
    lower = title.lower()
    return any(ex.lower() in lower for ex in EXCLUDE_TITLE_KEYWORDS)


def _title_matches_keyword(title: str, keyword: str) -> bool:
    """匹配窗口标题；短关键字避免误命中 opaivmplayer 等。"""
    import re

    title_lower = title.lower()
    keyword_lower = keyword.lower().strip()
    if not keyword_lower or _title_excluded(title):
        return False
    if keyword_lower not in title_lower:
        return False

    # "aivm" 会误匹配 "opaivmplayer"，需排除
    if keyword_lower == "aivm":
        if "opaivm" in title_lower and not re.search(r"(?:^|[-_\s])aivm", title_lower):
            return False

    # 短关键字要求词边界，避免子串误匹配
    if len(keyword_lower) <= 5:
        boundary = re.search(
            rf"(?<![a-z0-9]){re.escape(keyword_lower)}(?![a-z0-9])",
            title_lower,
        )
        prefixed = re.search(rf"{re.escape(keyword_lower)}[-_]", title_lower)
        if not boundary and not prefixed:
            return False
    return True


def _window_score(title: str, rect: Tuple[int, int, int, int]) -> float:
    """面积 + 游戏窗口标题加分。"""
    area = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
    lower = title.lower()
    bonus = 0.0
    for i, pref in enumerate(PREFER_TITLE_KEYWORDS):
        if pref.lower() in lower:
            bonus += (len(PREFER_TITLE_KEYWORDS) - i) * 5_000_000
    return area + bonus


def list_matching_windows(keyword: str) -> List[Tuple[str, Tuple[int, int, int, int], int]]:
    """列出标题包含关键字的可见窗口（标题, 矩形, hwnd）。"""
    if not win32gui:
        return []
    matches: List[Tuple[str, Tuple[int, int, int, int], int]] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        if _title_matches_keyword(title, keyword):
            matches.append((title, win32gui.GetWindowRect(hwnd), hwnd))
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass
    return matches


def find_window_match(keyword: str) -> Optional[Tuple[str, Tuple[int, int, int, int], int]]:
    """返回得分最高的匹配窗口 (title, rect, hwnd)。"""
    matches = list_matching_windows(keyword)
    if not matches:
        return None
    return max(matches, key=lambda item: _window_score(item[0], item[1]))


def find_window_rect(keyword: str) -> Optional[Tuple[int, int, int, int]]:
    """返回面积最大的匹配窗口（通常是游戏主窗口）。"""
    match = find_window_match(keyword)
    return match[1] if match else None


def find_window_title(keyword: str) -> str:
    match = find_window_match(keyword)
    return match[0] if match else ""


def find_window_hwnd(keyword: str) -> Optional[int]:
    match = find_window_match(keyword)
    return match[2] if match else None


def parse_region(s: str) -> Tuple[int, int, int, int]:
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("region 格式: left,top,width,height")
    left, top, width, height = parts
    return left, top, left + width, top + height


def get_virtual_screen_bounds(root: tk.Tk) -> Tuple[int, int, int, int]:
    """返回虚拟桌面范围 (x, y, width, height)。"""
    root.update_idletasks()
    return (
        root.winfo_vrootx(),
        root.winfo_vrooty(),
        root.winfo_vrootwidth(),
        root.winfo_vrootheight(),
    )


def clamp_geometry(
    root: tk.Tk,
    width: int,
    height: int,
    x: int,
    y: int,
    margin: int = 12,
) -> Tuple[int, int, int, int]:
    """把窗口尺寸和位置限制在可见桌面内。"""
    vx, vy, vw, vh = get_virtual_screen_bounds(root)
    width = max(360, min(width, vw - margin * 2))
    height = max(280, min(height, vh - margin * 2))
    max_x = vx + vw - width - margin
    max_y = vy + vh - height - margin
    x = max(vx + margin, min(x, max_x))
    y = max(vy + margin, min(y, max_y))
    return width, height, x, y


def safe_control_position(
    root: tk.Tk,
    game_rect: Optional[Tuple[int, int, int, int]],
    panel_w: int = 380,
    panel_h: int = 148,
) -> Tuple[int, int, int, int]:
    """控制条：贴游戏窗口底部外侧。"""
    vx, vy, vw, vh = get_virtual_screen_bounds(root)
    if game_rect:
        left, top, right, bottom = game_rect
        x = max(vx + 8, min(left, vx + vw - panel_w - 8))
        y = min(bottom + 6, vy + vh - panel_h - 8)
        if y + panel_h > vy + vh:
            y = max(vy + 8, top - panel_h - 6)
        return clamp_geometry(root, panel_w, panel_h, x, y)
    return clamp_geometry(root, panel_w, panel_h, vx + vw - panel_w - 24, vy + vh - panel_h - 24)


def set_window_click_through(window: tk.Toplevel, enable: bool = True) -> None:
    """翻译层鼠标穿透；框选层需 enable=False 以接收鼠标。"""
    try:
        window.update_idletasks()
        wid = window.winfo_id()
        hwnd = ctypes.windll.user32.GetParent(wid) or wid
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enable:
            style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style = (style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception as exc:
        print(f"[overlay] click-through failed: {exc}", flush=True)


@dataclass
class RegionTranslation:
    """用户框选区域及其翻译（坐标为游戏窗口客户区）。"""
    rect: Tuple[int, int, int, int]
    source_text: str
    translated: str
    offset_x: int = 0
    offset_y: int = 0
    is_paragraph: bool = False
    block_id: str = ""

    def __post_init__(self) -> None:
        if not self.block_id:
            x1, y1, x2, y2 = self.rect
            raw = f"{self.source_text}|{x1}|{y1}|{x2}|{y2}"
            self.block_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]




class OverlayApp:
    def __init__(self, cfg: AppConfig, region: Optional[Tuple[int, int, int, int]] = None):
        self.cfg = cfg
        self.fixed_region = region
        self.cache = TranslationCache(CACHE_PATH)
        self.translator_engine = cfg.translate_engine
        self.pipeline: Optional[KoreanOcrPipeline] = None
        self._pipeline_ready = threading.Event()
        self._stop = threading.Event()
        self._regions: List[RegionTranslation] = []
        self._lock = threading.Lock()
        self._busy = False
        self._capture_title = ""
        self._capture_hwnd: Optional[int] = None
        self._last_monitor: Optional[dict] = None
        self._overlay_geom = ""
        self._show_overlay = False
        self._selecting = False
        self._sel_start: Optional[Tuple[int, int]] = None
        self._sel_rect_id: Optional[int] = None
        self._sel_monitor: Optional[dict] = None
        self._drag_mode = False
        self._drag_target: Optional[RegionTranslation] = None
        self._drag_last: Optional[Tuple[int, int]] = None
        self._overlay_dirty = False
        self._redraw_scheduled = False

        self.root = tk.Tk()
        self.root.title("Trickcal 即时翻译 v1.5")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg="#1a1a1a")
        self.root.update_idletasks()
        w, h, x, y = safe_control_position(self.root, None)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.status = tk.Label(
            self.root,
            text="正在加载 OCR 引擎...",
            fg="#ddd",
            bg="#1a1a1a",
            anchor="w",
            wraplength=350,
            font=("Microsoft YaHei UI", 9),
        )
        self.status.pack(fill=tk.X, padx=8, pady=6)

        btn_row = tk.Frame(self.root, bg="#1a1a1a")
        btn_row.pack(fill=tk.X, padx=4, pady=2)
        tk.Button(btn_row, text="框选翻译", command=self.start_region_select, width=9).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_row, text="调整位置", command=self.toggle_drag_mode, width=9).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_row, text="清除翻译", command=self.clear_translations, width=9).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_row, text="对齐游戏", command=self.reset_position, width=9).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_row, text="隐藏/显示", command=self.toggle_overlay, width=9).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_row, text="退出", command=self.shutdown, width=6).pack(side=tk.RIGHT, padx=3)

        hint = tk.Label(
            self.root,
            text=f"框选底部韩文 | 最多保留 {self.cfg.max_overlay_regions} 条翻译",
            fg="#888",
            bg="#1a1a1a",
            anchor="w",
            wraplength=350,
            font=("Microsoft YaHei UI", 8),
        )
        hint.pack(fill=tk.X, padx=8, pady=(0, 6))

        # 游戏窗口内浮动翻译层（透明、穿透鼠标）
        self.overlay = tk.Toplevel(self.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.overlay.configure(bg=TRANSPARENT_COLOR)
        self.overlay_canvas = tk.Canvas(
            self.overlay, bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0
        )
        self.overlay_canvas.pack(fill=tk.BOTH, expand=True)

        # 框选层（与游戏同尺寸，可接收鼠标）
        self.selector = tk.Toplevel(self.root)
        self.selector.withdraw()
        self.selector.overrideredirect(True)
        self.selector.attributes("-topmost", True)
        self.selector.attributes("-alpha", 0.28)
        self.selector.configure(bg="#000000")
        self.selector_canvas = tk.Canvas(
            self.selector, bg="#000000", highlightthickness=0, bd=0, cursor="crosshair"
        )
        self.selector_canvas.pack(fill=tk.BOTH, expand=True)
        self.selector_canvas.bind("<ButtonPress-1>", self._on_sel_press)
        self.selector_canvas.bind("<B1-Motion>", self._on_sel_motion)
        self.selector_canvas.bind("<ButtonRelease-1>", self._on_sel_release)
        self.selector.bind("<Escape>", self._cancel_select)

        self.overlay_canvas.bind("<ButtonPress-1>", self._on_label_press)
        self.overlay_canvas.bind("<B1-Motion>", self._on_label_motion)
        self.overlay_canvas.bind("<ButtonRelease-1>", self._on_label_release)

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.overlay.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.selector.protocol("WM_DELETE_WINDOW", self._cancel_select)
        self.root.update_idletasks()
        self.root.lift()
        self.root.after(300, lambda: set_window_click_through(self.overlay, True))
        self.root.after(400, self.reset_position)
        print("[translator] v1.5 Frida ko-zh pairs + CN string DB", flush=True)
        threading.Thread(target=self._init_pipeline_async, daemon=True).start()

    def _init_pipeline_async(self) -> None:
        try:
            print("[translator] Initializing OCR engine...", flush=True)
            self.root.after(0, lambda: self.status.config(
                text="正在加载 OCR 引擎...\nPaddle 不可用时会加载 EasyOCR\n首次请先运行 download_models.bat"
            ))
            pipeline = KoreanOcrPipeline(
                fast_mode=self.cfg.fast_mode,
                coverage_boost=self.cfg.coverage_boost,
            )
            self.pipeline = pipeline
            if pipeline.ready:
                engines = []
                if pipeline._paddle:
                    ptag = "GPU" if pipeline.paddle_gpu else "CPU"
                    engines.append(f"PaddleOCR({ptag})★")
                if pipeline._easyocr:
                    gpu_tag = "GPU" if pipeline.use_gpu else "CPU"
                    engines.append(f"EasyOCR({gpu_tag})备用")
                if pipeline._rapid and not pipeline._paddle and not pipeline._easyocr:
                    engines.append("RapidOCR")
                dev = f" | 设备: {pipeline.device_label[:28]}"
                primary = pipeline.primary_ocr
                db = get_game_string_db()
                ko_db = get_ko_zh_db()
                db_tag = f" | 国服文本 {db.count}条" if db.available else " | 国服文本未构建"
                ko_tag = f" | 韩中表 {ko_db.count}条" if ko_db.available else ""
                msg = f"就绪 | {', '.join(engines)}{dev}{db_tag}{ko_tag}\n主 OCR: {primary} | 点「框选翻译」拖拽选区"
                if pipeline._paddle and pipeline.use_gpu and not pipeline.paddle_gpu:
                    msg += "\n⚠ Paddle 为 CPU 版，运行 install_paddle_gpu.bat 可加速"
                elif pipeline._easyocr and not pipeline.use_gpu:
                    msg += "\n⚠ 当前 CPU 模式很慢，请运行 install_gpu_torch.bat 启用 GPU"
                print(f"[translator] {msg}", flush=True)
            else:
                msg = "OCR 未就绪，请重新运行 start.bat 安装依赖"
                print(f"[translator] ERROR: OCR not ready", flush=True)
            self.root.after(0, lambda: self.status.config(text=msg))
        except Exception as exc:
            err = f"OCR 加载失败: {exc}"
            print(f"[translator] {err}", flush=True)
            self.root.after(0, lambda: self.status.config(text=err))
        finally:
            self._pipeline_ready.set()

    def _apply_geometry(self, width: int, height: int, x: int, y: int) -> None:
        w, h, x, y = clamp_geometry(self.root, width, height, x, y)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def reset_position(self) -> None:
        rect = self.fixed_region or find_window_rect(self.cfg.window_keyword)
        w, h, x, y = safe_control_position(self.root, rect)
        self._apply_geometry(w, h, x, y)
        self._sync_overlay_geometry(force=True)
        self.status.config(text="控制条已对齐 | 点「框选翻译」开始")

    def start_region_select(self) -> None:
        if not self._pipeline_ready.is_set() or not self.pipeline or not self.pipeline.ready:
            self.status.config(text="OCR 尚未就绪，请稍候")
            return
        if self._busy:
            self.status.config(text="正在处理上一块选区，请稍候")
            return
        monitor = self._capture_region()
        if not monitor:
            self.status.config(text=f"未找到窗口 '{self.cfg.window_keyword}'")
            return
        self._sel_monitor = monitor
        x, y = monitor["left"], monitor["top"]
        w, h = monitor["width"], monitor["height"]
        if w < 80 or h < 80:
            self.status.config(text="游戏窗口太小，无法框选")
            return
        self._selecting = True
        self._sel_start = None
        self.selector.geometry(f"{w}x{h}+{x}+{y}")
        self.selector.deiconify()
        self.selector.lift()
        self.selector.attributes("-topmost", True)
        set_window_click_through(self.selector, False)
        self.selector_canvas.delete("all")
        self.selector_canvas.create_text(
            w // 2, 22,
            text="拖拽框选要翻译的文字区域  |  ESC 取消",
            fill="#FFE082",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.status.config(text="框选模式：在游戏窗口拖拽矩形")

    def _cancel_select(self, _event=None) -> None:
        self._selecting = False
        self._sel_start = None
        self._sel_rect_id = None
        try:
            self.selector.withdraw()
        except Exception:
            pass
        if not self._busy:
            self.status.config(text="已取消框选")

    def _on_sel_press(self, event) -> None:
        self._sel_start = (event.x, event.y)
        if self._sel_rect_id is not None:
            self.selector_canvas.delete(self._sel_rect_id)
        self._sel_rect_id = self.selector_canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#FFD54F", width=2, dash=(4, 2),
        )

    def _on_sel_motion(self, event) -> None:
        if not self._sel_start or self._sel_rect_id is None:
            return
        x0, y0 = self._sel_start
        self.selector_canvas.coords(self._sel_rect_id, x0, y0, event.x, event.y)

    def _on_sel_release(self, event) -> None:
        if not self._sel_start or not self._sel_monitor:
            self._cancel_select()
            return
        x0, y0 = self._sel_start
        x1, y1 = min(x0, event.x), min(y0, event.y)
        x2, y2 = max(x0, event.x), max(y0, event.y)
        self._cancel_select()
        if x2 - x1 < 12 or y2 - y1 < 12:
            self.status.config(text="选区太小，请重新框选")
            return
        threading.Thread(
            target=self._translate_region,
            args=((x1, y1, x2, y2),),
            daemon=True,
        ).start()

    def toggle_drag_mode(self) -> None:
        with self._lock:
            has = bool(self._regions)
        if not has:
            self.status.config(text="暂无翻译可调整")
            return
        self._drag_mode = not self._drag_mode
        self._drag_target = None
        self._drag_last = None
        if self._drag_mode:
            self._show_overlay = True
            self._sync_overlay_geometry(force=True)
            self._apply_overlay_input_mode()
            self._schedule_paint()
            self.status.config(text="调整位置：拖动译文 → 再点「调整位置」结束")
        else:
            self._apply_overlay_input_mode()
            self._schedule_paint()
            self.status.config(text="已锁定位置（翻译层穿透，不影响游戏操作）")

    def _apply_overlay_input_mode(self) -> None:
        set_window_click_through(self.overlay, enable=not self._drag_mode)
        cursor = "fleur" if self._drag_mode else ""
        try:
            self.overlay_canvas.configure(cursor=cursor)
        except Exception:
            pass

    def _display_rect(self, rt: RegionTranslation) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = rt.rect
        return x1 + rt.offset_x, y1 + rt.offset_y, x2 + rt.offset_x, y2 + rt.offset_y

    def _region_at(self, x: int, y: int) -> Optional[RegionTranslation]:
        margin = 10
        with self._lock:
            for rt in reversed(self._regions):
                x1, y1, x2, y2 = self._display_rect(rt)
                if x1 - margin <= x <= x2 + margin and y1 - margin <= y <= y2 + margin:
                    return rt
        return None

    def _on_label_press(self, event) -> None:
        if not self._drag_mode:
            return
        rt = self._region_at(event.x, event.y)
        if rt:
            self._drag_target = rt
            self._drag_last = (event.x, event.y)

    def _on_label_motion(self, event) -> None:
        if not self._drag_mode or not self._drag_target or not self._drag_last:
            return
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        if dx == 0 and dy == 0:
            return
        tag = f"rt_{self._drag_target.block_id}"
        self.overlay_canvas.move(tag, dx, dy)
        self._drag_target.offset_x += dx
        self._drag_target.offset_y += dy
        self._drag_last = (event.x, event.y)

    def _on_label_release(self, _event) -> None:
        self._drag_target = None
        self._drag_last = None

    def clear_translations(self) -> None:
        self._drag_mode = False
        self._drag_target = None
        with self._lock:
            self._regions.clear()
        self._show_overlay = False
        self.overlay_canvas.delete("all")
        self.overlay.withdraw()
        self.status.config(text="已清除全部翻译")

    def _schedule_paint(self) -> None:
        if self._redraw_scheduled:
            return
        self._redraw_scheduled = True
        self.root.after_idle(self._paint_overlay)

    def _paint_one_region(self, rt: RegionTranslation) -> None:
        if not self._show_overlay:
            return
        self._sync_overlay_geometry()
        self._draw_region_label(rt)

    def _paint_overlay(self) -> None:
        self._redraw_scheduled = False
        with self._lock:
            has_regions = bool(self._regions)
            regions = list(self._regions[-self.cfg.max_overlay_regions:])
        if not self._show_overlay or not has_regions:
            try:
                self.overlay.withdraw()
            except Exception:
                pass
            return
        self._sync_overlay_geometry()
        self.overlay_canvas.delete("all")
        ow = self.overlay_canvas.winfo_width()
        if ow <= 1:
            self.root.after(80, self._schedule_paint)
            return
        for rt in regions:
            self._draw_region_label(rt)

    def toggle_overlay(self) -> None:
        with self._lock:
            has = bool(self._regions)
        if not has:
            self.status.config(text="暂无翻译可显示")
            return
        self._show_overlay = not self._show_overlay
        if self._show_overlay:
            self._sync_overlay_geometry(force=True)
            self._schedule_paint()
            self.status.config(text="翻译层已显示（可穿透点击游戏）")
        else:
            self.overlay.withdraw()
            self.status.config(text="翻译层已隐藏")

    def _sync_overlay_geometry(self, force: bool = False) -> None:
        with self._lock:
            has_regions = bool(self._regions)
        if not self._show_overlay or not has_regions:
            try:
                self.overlay.withdraw()
            except Exception:
                pass
            return
        monitor = self._last_monitor
        if not monitor:
            match = find_window_match(self.cfg.window_keyword)
            if not match:
                return
            _, rect, _ = match
            left, top, right, bottom = rect
            monitor = {
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
            }
        x, y = monitor["left"], monitor["top"]
        w, h = monitor["width"], monitor["height"]
        if w < 50 or h < 50:
            return
        geom = f"{w}x{h}+{x}+{y}"
        if not force and geom == self._overlay_geom:
            return
        self._overlay_geom = geom
        self.overlay.geometry(geom)
        self.overlay.deiconify()
        self.overlay.attributes("-topmost", True)
        self._apply_overlay_input_mode()

    def shutdown(self) -> None:
        self._stop.set()
        self.cache.save()
        try:
            self.selector.destroy()
        except Exception:
            pass
        try:
            self.overlay.destroy()
        except Exception:
            pass
        self.root.destroy()

    def _translate_region(self, window_rect: Tuple[int, int, int, int]) -> None:
        if not self._pipeline_ready.is_set() or not self.pipeline or not self.pipeline.ready:
            return
        if self._busy:
            return
        self._busy = True
        try:
            monitor = self._capture_region()
            if not monitor:
                self.root.after(0, lambda: self.status.config(text="未找到游戏窗口"))
                return

            self.root.after(0, lambda: self.status.config(text="识别选中区域..."))

            bgr, method = capture_game_window_roi(
                self._capture_hwnd, monitor, window_rect
            )
            if bgr is None:
                err = "截屏失败：请把游戏窗口置于最前后再框选"
                self.root.after(0, lambda: self.status.config(text=err))
                return

            cap_h, cap_w = bgr.shape[:2]
            full_roi = (0, 0, cap_w, cap_h)
            likely_paragraph = roi_is_paragraph(cap_h, cap_w)
            hits, raw_source, is_paragraph = self.pipeline.recognize_roi(
                bgr, full_roi, compact=not likely_paragraph,
            )
            if not raw_source:
                hint = "选区内未识别到韩文，请扩大选区重试"
                if cap_h >= 55 and cap_w >= 160:
                    hint = "选区内未识别到韩文，请框住完整弹窗文字后重试"
                self.root.after(0, lambda h=hint: self.status.config(text=h))
                return

            candidates = [h.text for h in hits]
            if is_paragraph or "\n" in raw_source:
                source = raw_source.strip()
            else:
                source = resolve_ui_ko_label(raw_source, candidates)
            translated = self._translate(source, candidates, paragraph=is_paragraph)
            if not translated:
                gloss_try = translate_glossary_from_pool(raw_source, candidates)
                if gloss_try:
                    translated = gloss_try
                    source = resolve_ui_ko_label(raw_source, candidates)
            if not translated:
                self.root.after(
                    0,
                    lambda rs=raw_source, s=source, p=is_paragraph: self.status.config(
                        text=(
                            f"未能翻译\nOCR原始:{rs} → 归一:{s}\n"
                            + ("请框住完整弹窗/说明文字" if p else "请只框底部韩文标签")
                        )
                    ),
                )
                return
            if contains_hangul(translated):
                self.root.after(
                    0,
                    lambda: self.status.config(
                        text="翻译仍含韩文，请缩小选区只框一段文字后重试"
                    ),
                )
                return

            entry = RegionTranslation(
                rect=window_rect,
                source_text=source,
                translated=translated,
                is_paragraph=is_paragraph,
            )
            with self._lock:
                if len(self._regions) >= self.cfg.max_overlay_regions:
                    self.root.after(
                        0,
                        lambda m=self.cfg.max_overlay_regions: self.status.config(
                            text=f"已达上限 {m} 条，请先「清除翻译」"
                        ),
                    )
                    return
                self._regions.append(entry)
                region_count = len(self._regions)
            self._last_monitor = monitor
            self._show_overlay = True
            self.root.after(0, self._finish_region_paint)
            preview = translated if len(translated) <= 28 else translated[:27] + "…"
            src_hint = source if len(source) <= 16 else source[:15] + "…"
            ts = time.strftime("%H:%M:%S")
            self.root.after(
                0,
                lambda p=preview, sh=src_hint, c=region_count, t=ts: self.status.config(
                    text=f"[{t}] {p}\n识别: {sh} | 共 {c} 块"
                ),
            )
        except Exception as exc:
            err = f"处理选区出错: {exc}"
            print(f"[translator] {err}", flush=True)
            self.root.after(0, lambda: self.status.config(text=err))
        finally:
            self._busy = False

    def _finish_region_paint(self) -> None:
        """翻译完成后同步 overlay 尺寸并重绘全部区域（避免 canvas 宽度为 0 时只显示在状态栏）。"""
        self._sync_overlay_geometry(force=True)
        self._schedule_paint()

    def _capture_region(self) -> Optional[dict]:
        self._capture_hwnd = None
        if self.fixed_region:
            left, top, right, bottom = self.fixed_region
            self._capture_title = "fixed region"
        else:
            match = find_window_match(self.cfg.window_keyword)
            if not match:
                self._capture_title = ""
                return None
            title, rect, hwnd = match
            left, top, right, bottom = rect
            self._capture_title = title
            self._capture_hwnd = hwnd
        w, h = right - left, bottom - top
        if w < 100 or h < 100:
            return None
        return {"left": left, "top": top, "width": w, "height": h}

    def _translate(
        self,
        text: str,
        candidates: Optional[List[str]] = None,
        *,
        paragraph: bool = False,
    ) -> str:
        text = text.strip()
        if not candidates:
            candidates = [text]
        cache_key = _compact_ko(text)
        if self.cfg.use_cache and not paragraph:
            for key in (cache_key, text):
                cached = self.cache.get(key)
                if cached and not contains_hangul(cached):
                    cleaned = cached.strip("\"'""''「」『』")
                    if cleaned and cleaned not in ("杀死", "重生", "吻", "卡", "商店"):
                        return cleaned
        out = translate_ui_label(
            text,
            primary=self.translator_engine,
            fallback="alibaba",
            candidates=candidates,
            paragraph=paragraph,
        )
        out = out.strip("\"'""''「」『』") if out else out
        if self.cfg.use_cache and out and not contains_hangul(out):
            self.cache.set(cache_key, out)
        return out

    def _font_size_for_rect(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        text: str,
        *,
        is_paragraph: bool = False,
    ) -> int:
        """根据选区大小自适应字号。"""
        h = max(8, y2 - y1)
        w = max(8, x2 - x1)
        line_count = max(1, text.count("\n") + 1)
        if is_paragraph:
            base = min(h / (line_count * 1.35), w * 0.11)
            return max(9, min(13, int(base)))
        base = min(h * 0.42, w * 0.12)
        if len(text) > 24:
            base *= 0.88
        if len(text) > 48:
            base *= 0.82
        return max(9, min(12, int(base)))

    def _draw_outlined_text(
        self,
        x: int,
        y: int,
        text: str,
        font: tuple,
        inner_w: int,
        tag: str,
        *,
        anchor=tk.CENTER,
        justify=tk.CENTER,
    ) -> None:
        """醒目：粗体白字 + 深色描边（5 次绘制，减轻卡顿）。"""
        outline = "#4A148C"
        fill = "#FFFFFF"
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)):
            if dx == 0 and dy == 0:
                color = fill
            else:
                color = outline
            self.overlay_canvas.create_text(
                x + dx, y + dy,
                text=text,
                fill=color,
                font=font,
                width=inner_w,
                justify=justify,
                anchor=anchor,
                tags=(tag,),
            )

    def _draw_region_label(self, rt: RegionTranslation) -> None:
        x1, y1, x2, y2 = self._display_rect(rt)
        if x2 <= x1 or y2 <= y1:
            return
        label = rt.translated or rt.source_text
        if not label:
            return

        pad = 4
        inner_w = max(20, x2 - x1 - pad * 2)
        fs = self._font_size_for_rect(
            x1, y1, x2, y2, label, is_paragraph=rt.is_paragraph,
        )
        font = ("Microsoft YaHei UI", fs, "bold")
        tag = f"rt_{rt.block_id}"

        if rt.is_paragraph:
            cx = x1 + pad
            cy = y1 + pad
            anchor = tk.NW
            justify = tk.LEFT
        else:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            anchor = tk.CENTER
            justify = tk.CENTER

        if self._drag_mode:
            self.overlay_canvas.create_rectangle(
                x1, y1, x2, y2, outline="#80D8FF", width=1, dash=(3, 2), tags=(tag,),
            )

        self._draw_outlined_text(cx, cy, label, font, inner_w, tag, anchor=anchor, justify=justify)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    user = load_user_config()
    parser = argparse.ArgumentParser(description="Trickcal 即时 OCR 翻译 v1.1")
    parser.add_argument("--window", default=user.get("window", "trickcal"), help="窗口标题关键字")
    parser.add_argument("--region", default=user.get("region", ""), help="捕获区域 left,top,width,height")
    parser.add_argument("--interval", type=float, default=float(user.get("interval", 1.2)), help="刷新间隔(秒)")
    parser.add_argument("--engine", default=user.get("engine", "bing"), choices=["bing", "alibaba", "baidu", "google"])
    parser.add_argument("--no-fast-mode", action="store_true", help="关闭分区快速 OCR（更全但更慢）")
    parser.add_argument("--no-subtitle-boost", action="store_true", help="关闭字幕增强预处理")
    parser.add_argument("--no-coverage-boost", action="store_true", help="关闭全屏兜底扫描（更快但识别更少）")
    parser.add_argument("--max-regions", type=int, default=int(user.get("max_regions", 40)), help="最多同时显示翻译条数")
    parser.add_argument("--list-windows", action="store_true", help="列出匹配窗口后退出")
    args = parser.parse_args()

    if args.list_windows:
        print(f"Searching windows containing: {args.window!r}\n")
        for title, rect, _hwnd in list_matching_windows(args.window):
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            print(f"  {w}x{h}  {title}")
        if not list_matching_windows(args.window):
            print("  (none found)")
            print("\nTry: --list-windows with keywords: trickcal, aivm-x, 异世界")
        return

    cfg = AppConfig(
        window_keyword=args.window,
        poll_interval=args.interval,
        translate_engine=args.engine,
        subtitle_boost=not args.no_subtitle_boost,
        fast_mode=not args.no_fast_mode,
        coverage_boost=not args.no_coverage_boost,
        max_overlay_regions=max(5, min(100, args.max_regions)),
    )
    region = parse_region(args.region) if args.region else None
    OverlayApp(cfg, region).run()


if __name__ == "__main__":
    main()
