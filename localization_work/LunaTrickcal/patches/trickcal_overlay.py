# Trickcal: floating translation on OCR regions — transparent, draggable.
import functools
import time
from traceback import print_exc

import gobject
import trickcal_regions
import windows
from myutils.config import globalconfig, saveallconfig
from qtsymbols import *

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010


def _log(msg: str) -> None:
    try:
        path = gobject.getconfig("trickcal_overlay.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [overlay] {msg}\n")
    except Exception:
        pass


def _rect_key(rect) -> str:
    return trickcal_regions.rect_key(rect)


def _rect_overlap(a, b) -> float:
    return trickcal_regions.rect_overlap_ratio(a, b)


def _find_bubble_key(select_rect) -> str | None:
    mgr = get_overlay()
    if not mgr._bubbles:
        return None
    select_rect = trickcal_regions.copy_rect(select_rect)
    if not select_rect:
        return None
    best_key = None
    best_score = 0.0
    for key, bubble in mgr._bubbles.items():
        score = _rect_overlap(select_rect, bubble._base_rect)
        if score > best_score:
            best_score = score
            best_key = key
    if best_key and best_score >= 0.08:
        return best_key
    sx, sy = trickcal_regions.rect_center(select_rect)
    best_key = None
    best_dist = 1e18
    for key, bubble in mgr._bubbles.items():
        cx, cy = trickcal_regions.rect_center(bubble._base_rect)
        d = (cx - sx) ** 2 + (cy - sy) ** 2
        if d < best_dist:
            best_dist = d
            best_key = key
    if best_key and best_dist <= 140**2:
        return best_key
    return None


def _cancel_pending_for_rect(rect) -> None:
    global _translate_queue, _translate_pending
    rk = _rect_key(rect)
    _translate_queue = [t for t in _translate_queue if _rect_key(t[0]) != rk]
    _translate_pending = {k for k in _translate_pending if not k.startswith(rk + "|")}


def _remove_luna_persistent_range(rect) -> bool:
    try:
        ts = getattr(gobject.base, "textsource", None)
        if not ts or not hasattr(ts, "ranges"):
            return False
        removed = False
        for rm in list(ts.ranges):
            rrect = getattr(rm, "trickcal_crop_rect", None) or trickcal_regions.rect_from_range_ui(
                rm.range_ui
            )
            if not rrect:
                continue
            if trickcal_regions.rects_close(rrect, rect) or _rect_overlap(rect, rrect) >= 0.25:
                try:
                    rm.range_ui.hide()
                except Exception:
                    pass
                try:
                    rm.range_ui.closesignal.emit()
                except Exception:
                    pass
                ts.ranges.remove(rm)
                removed = True
        if removed:
            globalconfig["ocrregions"] = [
                getattr(rm, "trickcal_crop_rect", None) or rm.range_ui.getrect()
                for rm in ts.ranges
                if rm.range_ui.getrect()
            ]
        return removed
    except Exception:
        print_exc()
        return False


def _load_offset(rect) -> tuple[int, int]:
    offsets = globalconfig.get("trickcal_overlay_offsets") or {}
    val = offsets.get(_rect_key(rect))
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return int(val[0]), int(val[1])
    return 0, 0


def _save_offset(rect, ox: int, oy: int) -> None:
    offsets = globalconfig.setdefault("trickcal_overlay_offsets", {})
    offsets[_rect_key(rect)] = [int(ox), int(oy)]
    try:
        saveallconfig()
    except Exception:
        pass


def _global_pos(event: QMouseEvent) -> QPoint:
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def _build_overlay_items(regions, translation: str):
    res = (translation or "").strip()
    if not res or not regions:
        return []
    if len(regions) == 1:
        return [{"rect": regions[0]["rect"], "text": res}]
    parts = [p.strip() for p in res.split("\n") if p.strip()]
    if len(parts) == len(regions):
        return [{"rect": regions[i]["rect"], "text": parts[i]} for i in range(len(regions))]
    return []


class FloatingBubble(QWidget):
    """Screen-positioned via MoveWindow (physical px, same as Luna OCR range UI)."""

    def __init__(self, rect, text: str):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._base_rect = trickcal_regions.copy_rect(rect)
        (x1, y1), (x2, y2) = self._base_rect
        self._x1, self._x2 = int(min(x1, x2)), int(max(x1, x2))
        self._y1, self._y2 = int(min(y1, y2)), int(max(y1, y2))
        self._region_w = max(24, self._x2 - self._x1)
        self._region_h = max(16, self._y2 - self._y1)
        self._dragging = False
        self._drag_anchor = QPoint()
        self._win_origin = (0, 0, 0, 0)
        self._saved_ox, self._saved_oy = _load_offset(self._base_rect)

        font = QFont()
        font.setPointSize(int(globalconfig.get("trickcal_overlay_font_size", 16)))
        font.setBold(True)
        self._label = QLabel("", self)
        self._label.setFont(font)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "QLabel { color: #FFE066; background: transparent; padding: 2px 4px; }"
        )
        shadow = QGraphicsDropShadowEffect(self._label)
        shadow.setBlurRadius(6)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(1, 1)
        self._label.setGraphicsEffect(shadow)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._apply_text_layout(text)
        self.show()

    def _max_width(self) -> int:
        return max(self._region_w, min(480, self._region_w * 2))

    def _max_height(self) -> int:
        return max(self._region_h * 4, 160)

    def _apply_text_layout(self, text: str) -> None:
        font = self._label.font()
        fm = QFontMetrics(font)
        max_w = self._max_width()
        label_w = max(40, max_w - 4)
        bounds = fm.boundingRect(
            0,
            0,
            label_w,
            self._max_height(),
            int(Qt.TextFlag.TextWordWrap),
            text,
        )
        self._phys_w = max(self._region_w, min(max_w, bounds.width() + 12, max_w))
        label_w = max(40, self._phys_w - 4)
        bounds = fm.boundingRect(
            0,
            0,
            label_w,
            self._max_height(),
            int(Qt.TextFlag.TextWordWrap),
            text,
        )
        self._phys_h = max(
            self._region_h,
            min(self._max_height(), bounds.height() + 10),
            28,
        )
        self._label.setText(text)
        self._label.setFixedSize(label_w, max(20, self._phys_h - 4))
        self.setFixedSize(self._phys_w, self._phys_h)

    def update_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text or text == self._label.text():
            return
        self._apply_text_layout(text)
        if self.isVisible() and not self._dragging:
            px, py = self._default_pos()
            wr = windows.GetWindowRect(int(self.winId()))
            if abs(wr[0] - px) > 2 or abs(wr[1] - py) > 2:
                self._move_phys(px, py)
            else:
                self._move_phys(wr[0], wr[1])

    def _default_pos(self) -> tuple[int, int]:
        cx = (self._x1 + self._x2) // 2
        cy = (self._y1 + self._y2) // 2
        px = cx - self._phys_w // 2 + self._saved_ox
        py = cy - self._phys_h // 2 + self._saved_oy
        return int(px), int(py)

    def _move_phys(self, px: int, py: int) -> None:
        hwnd = int(self.winId())
        windows.MoveWindow(hwnd, int(px), int(py), self._phys_w, self._phys_h, True)
        windows.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            int(px),
            int(py),
            self._phys_w,
            self._phys_h,
            SWP_NOACTIVATE,
        )

    def showEvent(self, event):
        super().showEvent(event)
        px, py = self._default_pos()
        self._move_phys(px, py)
        if globalconfig.get("trickcal_overlay_clickthrough", False) and not self._dragging:
            QTimer.singleShot(120, self._apply_clickthrough)

    def _apply_clickthrough(self):
        if self._dragging:
            return
        try:
            hwnd = int(self.winId())
            windows.MouseTrans.set(hwnd)
        except Exception:
            print_exc()

    def _unset_clickthrough(self):
        try:
            windows.MouseTrans.unset(int(self.winId()))
        except Exception:
            print_exc()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            QTimer.singleShot(0, lambda b=self: delete_bubble_widget(b))
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._unset_clickthrough()
        self._drag_anchor = _global_pos(event)
        self._win_origin = windows.GetWindowRect(int(self.winId()))
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._dragging:
            return
        gp = _global_pos(event)
        dx = gp.x() - self._drag_anchor.x()
        dy = gp.y() - self._drag_anchor.y()
        wr = self._win_origin
        self._move_phys(wr[0] + dx, wr[1] + dy)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self._dragging or event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        wr = windows.GetWindowRect(int(self.winId()))
        cx = (self._x1 + self._x2) // 2
        cy = (self._y1 + self._y2) // 2
        base_px = cx - self._phys_w // 2
        base_py = cy - self._phys_h // 2
        self._saved_ox = wr[0] - base_px
        self._saved_oy = wr[1] - base_py
        _save_offset(self._base_rect, self._saved_ox, self._saved_oy)
        if globalconfig.get("trickcal_overlay_clickthrough", False):
            QTimer.singleShot(120, self._apply_clickthrough)
        event.accept()


class TrickcalOverlayManager:
    def __init__(self):
        self._bubbles: dict[str, FloatingBubble] = {}

    def clear(self):
        for b in list(self._bubbles.values()):
            try:
                b.hide()
                b.deleteLater()
            except Exception:
                pass
        self._bubbles.clear()

    def remove_bubble(self, bubble: "FloatingBubble") -> bool:
        for key, b in list(self._bubbles.items()):
            if b is bubble:
                self._bubbles.pop(key, None)
                try:
                    b.hide()
                    b.deleteLater()
                except Exception:
                    print_exc()
                return True
        return False

    def remove_at_rect(self, select_rect) -> str | None:
        key = _find_bubble_key(select_rect)
        if not key:
            return None
        bubble = self._bubbles.pop(key, None)
        if bubble is not None:
            try:
                bubble.hide()
                bubble.deleteLater()
            except Exception:
                print_exc()
        return key

    def remove_by_base_rect(self, rect) -> str | None:
        rect = trickcal_regions.copy_rect(rect)
        if not rect:
            return None
        for key, bubble in list(self._bubbles.items()):
            if trickcal_regions.rects_close(bubble._base_rect, rect):
                self._bubbles.pop(key, None)
                try:
                    bubble.hide()
                    bubble.deleteLater()
                except Exception:
                    print_exc()
                return key
        return self.remove_at_rect(rect)

    def show_regions(self, items, replace_all: bool = False):
        if replace_all:
            keep = {_rect_key(it["rect"]) for it in items if it.get("rect")}
            for key in list(self._bubbles):
                if key not in keep:
                    try:
                        b = self._bubbles.pop(key)
                        b.hide()
                        b.deleteLater()
                    except Exception:
                        pass
        for it in items:
            rect, text = it.get("rect"), (it.get("text") or "").strip()
            if not rect or not text:
                continue
            key = _rect_key(rect)
            try:
                bubble = self._bubbles.get(key)
                if bubble is None:
                    self._bubbles[key] = FloatingBubble(rect, text)
                else:
                    bubble.update_text(text)
            except Exception:
                print_exc()


_manager = None
_recent_overlay = {}
_translate_queue: list[tuple] = []
_translate_busy = False
_translate_pending: set[str] = set()


def _translate_task_key(rect, source: str) -> str:
    return f"{_rect_key(rect)}|{(source or '').strip()}"


def _run_on_ui_thread(fn) -> None:
    try:
        app = QApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            QTimer.singleShot(0, fn)
            return
    except Exception:
        pass
    fn()


def translate_all_ocr_regions() -> None:
    """OCR every persistent range and queue translations (Qt main thread)."""
    try:
        ts = getattr(gobject.base, "textsource", None)
        if not ts or not hasattr(ts, "_collect_region_results"):
            return
        pairs, _ = ts._collect_region_results(False)
        if not pairs:
            _log("translate_all: no OCR pairs")
            return
        trickcal_regions.remember_multi_regions(pairs)
        n = 0
        for rm, res in pairs:
            if res.error or res.result.isocrtranslate:
                continue
            ko = (res.textonly or "").strip()
            if not ko:
                continue
            rect = getattr(rm, "trickcal_crop_rect", None) or trickcal_regions.rect_from_range_ui(
                rm.range_ui
            )
            if not rect:
                continue
            enqueue_region_translate(rect, ko)
            n += 1
        _log(f"translate_all: queued {n}/{len(pairs)} regions")
    except Exception:
        print_exc()


def enqueue_region_translate(rect, source: str) -> None:
    """Queue one region translation on the Qt main thread (safe from OCR worker threads)."""
    source = (source or "").strip()
    rect = trickcal_regions.copy_rect(rect)
    if not source or not rect:
        return
    key = _translate_task_key(rect, source)

    def _add():
        if key in _translate_pending:
            return
        _translate_pending.add(key)
        _translate_queue.append((rect, source, key))
        _pump_translate_queue()

    _run_on_ui_thread(_add)


def _pump_translate_queue() -> None:
    global _translate_busy
    if _translate_busy or not _translate_queue:
        return
    rect, source, key = _translate_queue.pop(0)
    _translate_busy = True
    trickcal_regions.remember_for_translate(rect, source)
    engine = globalconfig.get("toppest_translator")
    _log(f"queue translate src={source[:24]!r} rect={rect}")

    done = [False]

    def _finish(tr=None):
        global _translate_busy
        if done[0]:
            return
        done[0] = True
        try:
            zh = getattr(tr, "result", None) if tr else None
            if zh:
                show_region_sync(rect, source, zh, engine=engine or "")
            else:
                _log(f"queue empty result src={source[:24]!r}")
        except Exception:
            print_exc()
        finally:
            _translate_pending.discard(key)
            _translate_busy = False
            if _translate_queue:
                QTimer.singleShot(0, _pump_translate_queue)

    try:
        gobject.base.textgetmethod(
            source,
            is_auto_run=True,
            waitforresultcallback=_finish,
            waitforresultcallbackengine=engine,
        )
    except Exception:
        print_exc()
        _finish(None)


def clear_all() -> None:
    global _translate_queue, _translate_busy, _translate_pending, _recent_overlay
    _translate_queue.clear()
    _translate_busy = False
    _translate_pending.clear()
    _recent_overlay.clear()

    def _run():
        get_overlay().clear()
        _log("clear_all overlay bubbles")

    _run_on_ui_thread(_run)


def delete_bubble_widget(bubble) -> None:
    """Safely remove the overlay bubble the user right-clicked (avoid closing Luna)."""

    def _run():
        try:
            rect = trickcal_regions.copy_rect(getattr(bubble, "_base_rect", None))
            mgr = get_overlay()
            if not mgr.remove_bubble(bubble):
                return
            if not rect:
                return
            trickcal_regions.remove_region_by_rect(rect)
            _cancel_pending_for_rect(rect)
            try:
                _remove_luna_persistent_range(rect)
            except Exception:
                print_exc()
            _log(f"delete bubble {rect}")
        except Exception:
            print_exc()

    _run_on_ui_thread(_run)


def delete_region_at_rect(rect) -> bool:
    """Remove one OCR overlay + cached region (by overlap with selection rect)."""
    rect = trickcal_regions.copy_rect(rect)
    if not rect:
        return False

    def _run() -> bool:
        try:
            key = get_overlay().remove_at_rect(rect)
            target = rect
            if key:
                parsed = trickcal_regions._parse_rect_key(key)
                if parsed:
                    target = parsed
            trickcal_regions.remove_region_by_rect(target)
            _cancel_pending_for_rect(target)
            luna = _remove_luna_persistent_range(target)
            _log(f"delete region {target} bubble={key!r} luna={luna}")
            return bool(key or luna)
        except Exception:
            print_exc()
            return False

    app = QApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        return _run()
    result = [False]

    def _wrap():
        result[0] = _run()

    _run_on_ui_thread(_wrap)
    return result[0]


def start_delete_region_picker() -> None:
    """Hotkey entry: drag a box over the mistranslated OCR region to remove it."""
    try:
        from gui.rangeselect import rangeselct_function

        def on_select(rect, img=None):
            if rect:
                delete_region_at_rect(rect)

        rangeselct_function(on_select)
        _log("delete picker started")
    except Exception:
        print_exc()


def get_overlay():
    global _manager
    if _manager is None:
        _manager = TrickcalOverlayManager()
    return _manager


def show_translation_overlay(base, translation: str, engine: str = ""):
    if not globalconfig.get("trickcal_overlay_enable", True):
        return
    trans = (translation or "").strip()
    if not trans:
        return
    top = globalconfig.get("toppest_translator")
    if top and engine and engine != top:
        return

    def _run():
        try:
            raw = getattr(base, "currenttext_raw", "") or ""
            regions = trickcal_regions.get_regions_for_overlay(raw)
            items = _build_overlay_items(regions, trans)
            if not items:
                _log(
                    f"skip regions={len(regions)} raw={raw[:24]!r} engine={engine!r} "
                    f"translation={trans[:32]!r}"
                )
                return
            dedup_key = (raw, trans, str(items[0]["rect"]))
            now = time.time()
            if now - _recent_overlay.get(dedup_key, 0) < 0.8:
                return
            _recent_overlay[dedup_key] = now
            get_overlay().show_regions(items)
            (x1, y1), (x2, y2) = items[0]["rect"]
            ox, oy = _load_offset(items[0]["rect"])
            _log(
                f"show {len(items)} raw={raw[:24]!r} at ({x1},{y1})-({x2},{y2}) "
                f"off=({ox},{oy}) engine={engine!r} text={items[0]['text'][:32]!r}"
            )
        except Exception:
            print_exc()

    QTimer.singleShot(0, _run)


def show_region_sync(rect, source: str, translation: str, engine: str = ""):
    """Update one overlay bubble without relying on currenttext_raw (multi-region OCR)."""
    if not globalconfig.get("trickcal_overlay_enable", True):
        return
    trans = (translation or "").strip()
    source = (source or "").strip()
    if not trans or not rect:
        return
    top = globalconfig.get("toppest_translator")
    if top and engine and engine != top:
        return

    def _run():
        try:
            dedup_key = (source, trans, _rect_key(rect))
            now = time.time()
            if now - _recent_overlay.get(dedup_key, 0) < 0.8:
                return
            _recent_overlay[dedup_key] = now
            get_overlay().show_regions([{"rect": rect, "text": trans}])
            (x1, y1), (x2, y2) = rect
            _log(
                f"sync raw={source[:24]!r} at ({x1},{y1})-({x2},{y2}) "
                f"engine={engine!r} text={trans[:32]!r}"
            )
        except Exception:
            print_exc()

    QTimer.singleShot(0, _run)


def batch_translate_regions():
    try:
        base = gobject.base
        ts = base.textsource
        if not ts or not hasattr(ts, "gettextonce_per_region"):
            return
        regions = ts.gettextonce_per_region()
        valid = [(r, t) for r, t in regions if t and t.strip()]
        if not valid:
            return
        results = [None] * len(valid)
        pending = [len(valid)]

        def maybe_show():
            if pending[0] > 0:
                return
            items = [
                {"rect": valid[i][0], "text": results[i]}
                for i in range(len(valid))
                if results[i]
            ]
            get_overlay().show_regions(items, replace_all=True)

        for i, (rect, ko) in enumerate(valid):
            trickcal_regions.remember_for_translate(rect, ko)

            def _cb(tr, idx=i):
                try:
                    if tr and getattr(tr, "result", None):
                        results[idx] = tr.result
                except Exception:
                    print_exc()
                pending[0] -= 1
                maybe_show()

            base.textgetmethod(ko, is_auto_run=False, waitforresultcallback=_cb)
    except Exception:
        print_exc()


def _patch_range_select():
    try:
        import gui.rangeselect as rs

        if getattr(rs, "_trickcal_range_patched", False):
            return
        orig = rs.rangeselct_function

        def rangeselct_function(callback):
            def wrapped(rect, img=None):
                return callback(rect, img)

            return orig(wrapped)

        rs.rangeselct_function = rangeselct_function
        rs._trickcal_range_patched = True
        _log("patched rangeselct_function")
    except Exception:
        print_exc()


def _patch_ocr_do():
    try:
        from gui.translatorUI import TranslatorWindow

        if getattr(TranslatorWindow, "_trickcal_ocr_do_patched", False):
            return
        orig_do = TranslatorWindow.ocr_do_function

        def ocr_do_function(self, rect, img=None):
            try:
                if rect:
                    crop = trickcal_regions.copy_rect(rect)
                    gobject.base.trickcal_once_active = True
                    gobject.base.trickcal_once_rect = crop
            except Exception:
                print_exc()
            orig_do(self, rect, img)

        TranslatorWindow.ocr_do_function = ocr_do_function
        TranslatorWindow._trickcal_ocr_do_patched = True
        _log("patched ocr_do_function (thread-safe)")
    except Exception:
        print_exc()


def _patch_translator_ui():
    try:
        from gui.translatorUI import TranslatorWindow

        if getattr(TranslatorWindow, "_trickcal_afterrange_patched", False):
            return
        orig = TranslatorWindow.afterrange

        def afterrange(self, clear, rect, img=None):
            try:
                if clear:
                    trickcal_regions.clear_all()
                    clear_all()
            except Exception:
                print_exc()
            ret = orig(self, clear, rect, img)
            if (
                globalconfig.get("multiregion", False)
                and globalconfig.get("trickcal_translate_on_range_select", False)
                and not clear
            ):
                QTimer.singleShot(350, translate_all_ocr_regions)
            return ret

        TranslatorWindow.afterrange = afterrange
        TranslatorWindow._trickcal_afterrange_patched = True
        _log("patched TranslatorWindow.afterrange")
    except Exception:
        print_exc()


def _patch_hotkeys():
    """Inject delete-region hotkey without user manually adding a random UUID entry."""
    try:
        import gui.setting.hotkey as hk

        if getattr(hk, "_trickcal_hotkey_patched", False):
            return

        orig = hk.registrhotkeys
        name = "trickcal_delete_region"

        def registrhotkeys_hook(self):
            orig(self)
            try:
                qs = globalconfig.setdefault("quick_setting", {}).setdefault("all", {})
                entry = qs.setdefault(name, {})
                entry.setdefault("name", "删除单个OCR区域")
                entry.setdefault("use", True)
                entry.setdefault("keystring", "6")
                keys = globalconfig.setdefault("myquickkeys", [])
                if name not in keys:
                    keys.append(name)
                self.bindfunctions[name] = lambda: gobject.base.safeinvokefunction.emit(
                    start_delete_region_picker
                )
                hk.regist_or_not_key(self, name)
                _log("registered delete-region hotkey (6)")
            except Exception:
                print_exc()

        hk.registrhotkeys = registrhotkeys_hook
        hk._trickcal_hotkey_patched = True
    except Exception:
        print_exc()


def _try_register_delete_hotkey():
    settin = getattr(gobject.base, "settin_ui", None)
    if settin is None:
        return
    try:
        import gui.setting.hotkey as hk

        if hk.registrhotkeys.__name__ != "registrhotkeys_hook":
            _patch_hotkeys()
        hk.registrhotkeys(settin)
    except Exception:
        print_exc()


def _patch_clear_ocr():
    try:
        ui = getattr(gobject.base, "translation_ui", None)
        if ui is None or getattr(ui, "_trickcal_clear_hooked", False):
            return

        def _on_clear():
            try:
                trickcal_regions.clear_all()
                clear_all()
                _log("clear OCR hotkey: overlay + cache cleared")
            except Exception:
                print_exc()

        ui.clear_signal_1.connect(_on_clear)
        ui._trickcal_clear_hooked = True
        _log("hooked clear_signal_1")
    except Exception:
        print_exc()


def _rebind_textsource(base):
    ts = getattr(base, "textsource", None)
    if ts is not None:
        ts.textgetmethod = base.textgetmethod


def install(base):
    if getattr(base, "_trickcal_overlay_installed", False):
        _rebind_textsource(base)
        _patch_clear_ocr()
        return
    base._trickcal_overlay_installed = True
    base.trickcal_ocr_regions = []
    base.trickcal_region_cache = []
    base.trickcal_region_cache_time = 0
    base.trickcal_source_rect_map = {}
    _patch_range_select()
    _patch_ocr_do()
    _patch_translator_ui()
    _patch_hotkeys()
    _patch_clear_ocr()
    QTimer.singleShot(1500, _try_register_delete_hotkey)
    _log("trickcal overlay installed (early)")

    def on_translate(engine, res):
        try:
            if getattr(base, "trickcal_once_active", False):
                raw = getattr(base, "currenttext_raw", "") or ""
                rect = getattr(base, "trickcal_once_rect", None)
                if not rect:
                    hit = trickcal_regions.resolve_region_for_source(raw)
                    rect = hit["rect"] if hit else None
                if rect:
                    show_region_sync(rect, raw, res, engine=engine)
                base.trickcal_once_active = False
                base.trickcal_once_rect = None
                return
            ts = getattr(base, "textsource", None)
            if ts and hasattr(ts, "ranges") and len(getattr(ts, "ranges", []) or []) > 1:
                return
            show_translation_overlay(base, res, engine=engine)
        except Exception:
            print_exc()

    try:
        base.dispatch_translate.connect(on_translate)
    except Exception:
        print_exc()

    orig_starttextsource = base.starttextsource

    @functools.wraps(orig_starttextsource)
    def starttextsource_hook(*args, **kwargs):
        orig_starttextsource(*args, **kwargs)
        _rebind_textsource(base)
        _patch_clear_ocr()

    base.starttextsource = starttextsource_hook
    _rebind_textsource(base)

    orig_textgetmethod = base.textgetmethod

    @functools.wraps(orig_textgetmethod)
    def textgetmethod_hook(text, *args, **kwargs):
        try:
            if getattr(base, "trickcal_once_active", False):
                pass
            else:
                source = (text or "").strip()
                if not trickcal_regions.resolve_region_for_source(source):
                    if not trickcal_regions.get_regions():
                        trickcal_regions.remember_from_follow_rect()
                    trickcal_regions.remember_from_textsource(source=source)
        except Exception:
            print_exc()
        return orig_textgetmethod(text, *args, **kwargs)

    base.textgetmethod = textgetmethod_hook
    _rebind_textsource(base)
