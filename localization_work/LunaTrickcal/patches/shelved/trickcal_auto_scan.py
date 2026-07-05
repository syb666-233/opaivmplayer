# Trickcal: 绑定窗口后自动 OCR 识别韩文并翻译（无需手动框选区域）
from __future__ import annotations

import re
import time
from traceback import print_exc

import gobject
import NativeUtils
import trickcal_overlay
import trickcal_regions
import windows
from CVUtils import cvMat
from myutils.config import globalconfig
from myutils.ocrutil import imageCut, ocr_run
from myutils.wrapper import threader
from qtsymbols import *

HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")
_LOG = "trickcal_overlay.log"
_NOISE_MARKERS = ("OurPlay", "加速中", "电脑版", "ScreenSketch", "Microsoft")


def _log(msg: str) -> None:
    try:
        path = gobject.getconfig(_LOG)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [auto_scan] {msg}\n")
    except Exception:
        pass


def _cfg(key: str, default):
    return globalconfig.get(key, default)


def _interval() -> float:
    custom = float(_cfg("trickcal_auto_scan_interval", 0) or 0)
    if custom > 0:
        return max(1.5, custom)
    return max(2.5, float(globalconfig.get("ocr_interval", 4.0)))


def _has_korean(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    for m in _NOISE_MARKERS:
        if m in text and len(HANGUL_RE.findall(text)) <= 2:
            return False
    hangul = len(HANGUL_RE.findall(text))
    if hangul >= 2:
        return True
    return hangul >= 1 and len(text) <= 16


def _score_block(text: str, rect) -> float:
    hangul = len(HANGUL_RE.findall(text))
    (x1, y1), (x2, y2) = rect
    area = max(1, abs(x2 - x1) * abs(y2 - y1))
    return hangul * 1000 + min(area, 5000)


def _dedupe_blocks(blocks: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    """合并高度重叠的 OCR 框，保留韩文更多的一条。"""
    kept: list[tuple[str, tuple]] = []
    for text, rect in sorted(blocks, key=lambda x: -_score_block(x[0], x[1])):
        dominated = False
        for _, kept_rect in kept:
            if trickcal_regions.rect_overlap_ratio(rect, kept_rect) >= 0.45:
                dominated = True
                break
        if not dominated:
            kept.append((text, rect))
    max_n = int(_cfg("trickcal_auto_scan_max_blocks", 8))
    return kept[:max_n]


def _box_to_screen_rect(box4, origin_x: int, origin_y: int):
    if not box4:
        return None
    x1, y1, x2, y2 = box4
    pad = int(_cfg("trickcal_auto_scan_box_pad", 4))
    sx1 = int(origin_x + min(x1, x2)) - pad
    sy1 = int(origin_y + min(y1, y2)) - pad
    sx2 = int(origin_x + max(x1, x2)) + pad
    sy2 = int(origin_y + max(y1, y2)) + pad
    if sx2 - sx1 < 8 or sy2 - sy1 < 8:
        return None
    return ((sx1, sy1), (sx2, sy2))


def _window_crop_rect(hwnd):
    wr = windows.GetWindowRect(hwnd)
    if not wr or len(wr) < 4:
        return None
    x1, y1, x2, y2 = int(wr[0]), int(wr[1]), int(wr[2]), int(wr[3])
    if x2 - x1 < 80 or y2 - y1 < 80:
        return None
    margin = int(_cfg("trickcal_auto_scan_margin", 0))
    x1 += margin
    y1 += margin
    x2 -= margin
    y2 -= margin
    if x2 <= x1 or y2 <= y1:
        return None
    return ((x1, y1), (x2, y2))


def _is_foreground(hwnd) -> bool:
    try:
        p1 = windows.GetWindowThreadProcessId(hwnd)
        p2 = windows.GetWindowThreadProcessId(windows.GetForegroundWindow())
        return p1 == p2
    except Exception:
        return True


class AutoScanManager:
    def __init__(self) -> None:
        self._stop = False
        self._last_scan = 0.0
        self._last_frame: cvMat | None = None
        self._text_cache: dict[str, str] = {}
        self._thread_started = False
        self._scan_counter = 0

    def start(self) -> None:
        if self._thread_started:
            return
        self._thread_started = True
        self._stop = False
        threader(self._loop)()
        _log("scan thread started")

    def stop(self) -> None:
        self._stop = True

    def reset_cache(self) -> None:
        self._last_frame = None
        self._text_cache.clear()
        self._last_scan = 0.0

    def wake_scan(self) -> None:
        """绑定窗口 / 清除浮层后：立即允许下一轮扫描。"""
        self._last_scan = 0.0
        self._last_frame = None

    def _should_run(self) -> bool:
        if not _cfg("trickcal_auto_scan", True):
            return False
        if not globalconfig.get("autorun", True):
            return False
        base = gobject.base
        if base is None:
            return False
        ts = getattr(base, "textsource", None)
        if ts is None or not hasattr(ts, "ranges"):
            return False
        if getattr(ts, "_pause_state", False):
            return False
        hwnd = getattr(ts, "hwnd", None)
        if not hwnd:
            return False
        if _cfg("trickcal_auto_scan_foreground_only", True) and not _is_foreground(hwnd):
            return False
        if _cfg("trickcal_auto_scan_only_when_no_regions", True):
            if getattr(ts, "ranges", None):
                return False
        return True

    def _loop(self) -> None:
        while not self._stop:
            try:
                if self._should_run():
                    now = time.time()
                    if now - self._last_scan >= _interval():
                        self._scan_once()
                        self._last_scan = now
            except Exception:
                print_exc()
            time.sleep(0.12)

    def _scan_once(self) -> None:
        ts = gobject.base.textsource
        hwnd = ts.hwnd
        crop = _window_crop_rect(hwnd)
        if not crop:
            return
        (x1, y1), (x2, y2) = crop
        succ, imgr = imageCut(hwnd, x1, y1, x2, y2)
        if imgr is None or imgr.isNull():
            return

        frame = cvMat.fromQImage(imgr)
        self._scan_counter += 1
        force = self._scan_counter % 5 == 0
        if self._last_frame is not None and not force:
            try:
                sim = frame.MSSIM(self._last_frame)
                if sim > float(_cfg("trickcal_auto_scan_frame_sim", 0.975)):
                    return
            except Exception:
                pass
        self._last_frame = frame

        result = ocr_run(imgr)
        if result.error:
            _log(f"ocr error: {result.error[:80]}")
            return
        if not result.result or not result.result.blocks:
            return

        min_side = int(_cfg("trickcal_auto_scan_min_box", 10))
        text_diff = int(globalconfig.get("ocr_text_diff", 8))
        seen_keys: set[str] = set()
        candidates: list[tuple[str, tuple]] = []

        if result.result.hasboxs:
            for block in result.result.blocks:
                text = (block.text or "").strip()
                if not _has_korean(text):
                    continue
                box4 = block.box4
                if not box4:
                    continue
                bw = abs(box4[2] - box4[0])
                bh = abs(box4[3] - box4[1])
                if bw < min_side or bh < min_side:
                    continue
                rect = _box_to_screen_rect(box4, x1, y1)
                if not rect:
                    continue
                candidates.append((text, rect))

            for text, rect in _dedupe_blocks(candidates):
                key = trickcal_regions.rect_key(rect)
                seen_keys.add(key)
                prev = self._text_cache.get(key)
                if prev is not None and NativeUtils.distance(prev, text) < text_diff:
                    continue
                self._text_cache[key] = text
                trickcal_overlay.enqueue_region_translate(rect, text)
        else:
            text = (result.textonly or "").strip()
            if _has_korean(text):
                rect = crop
                key = trickcal_regions.rect_key(rect)
                seen_keys.add(key)
                prev = self._text_cache.get(key)
                if prev is None or NativeUtils.distance(prev, text) >= text_diff:
                    self._text_cache[key] = text
                    trickcal_overlay.enqueue_region_translate(rect, text)

        stale = [k for k in self._text_cache if k not in seen_keys]
        if len(stale) > 40:
            for k in stale[:20]:
                self._text_cache.pop(k, None)

        if seen_keys:
            _log(f"queued scan pass, active blocks={len(seen_keys)}")


_manager: AutoScanManager | None = None


def get_manager() -> AutoScanManager:
    global _manager
    if _manager is None:
        _manager = AutoScanManager()
    return _manager


def _hook_textsource(base) -> None:
    ts = getattr(base, "textsource", None)
    if ts is None or getattr(ts, "_trickcal_auto_scan_hooked", False):
        return
    orig = ts.hwndChanged

    def hwndChanged(hwnd):
        mgr = get_manager()
        mgr.reset_cache()
        mgr.wake_scan()
        if hwnd:
            _log(f"hwnd bound {hwnd}, scan scheduled")
        return orig(hwnd)

    ts.hwndChanged = hwndChanged
    ts._trickcal_auto_scan_hooked = True


def install(base) -> None:
    if getattr(base, "_trickcal_auto_scan_installed", False):
        _hook_textsource(base)
        return
    base._trickcal_auto_scan_installed = True
    get_manager().start()

    orig_start = base.starttextsource

    def starttextsource_hook(*args, **kwargs):
        ret = orig_start(*args, **kwargs)
        _hook_textsource(base)
        return ret

    base.starttextsource = starttextsource_hook
    _hook_textsource(base)
    _log("auto scan installed")
