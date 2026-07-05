"""Windows 窗口截屏：BitBlt / PrintWindow 优先，避免 mss 误截重叠窗口。"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import mss
import numpy as np
from PIL import Image

try:
    import win32con
    import win32gui
    import win32ui
except ImportError:
    win32con = None
    win32gui = None
    win32ui = None

try:
    from ctypes import windll

    _user32 = windll.user32
except Exception:
    _user32 = None

PW_RENDERFULLCONTENT = 2


def _bitmap_to_bgr(save_bit_map) -> np.ndarray:
    bmpinfo = save_bit_map.GetInfo()
    bmpstr = save_bit_map.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr,
        "raw",
        "BGRX",
        0,
        1,
    )
    rgb = np.array(img)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _is_valid_capture(bgr: np.ndarray, min_mean: float = 8.0) -> bool:
    if bgr is None or bgr.size == 0:
        return False
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) >= min_mean


def capture_bitblt_window(hwnd: int) -> Optional[np.ndarray]:
    """从窗口 DC 直接 BitBlt（不受其他窗口遮挡影响）。"""
    if not win32gui or not win32ui or not win32con:
        return None
    hwnd_dc = mfc_dc = save_dc = save_bit_map = None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width < 8 or height < 8:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bit_map = win32ui.CreateBitmap()
        save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bit_map)
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)
        bgr = _bitmap_to_bgr(save_bit_map)
        return bgr if _is_valid_capture(bgr) else None
    except Exception as exc:
        print(f"[capture] BitBlt failed: {exc}", flush=True)
        return None
    finally:
        try:
            if save_bit_map is not None:
                win32gui.DeleteObject(save_bit_map.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if hwnd_dc is not None and win32gui:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def capture_printwindow(hwnd: int) -> Optional[np.ndarray]:
    """通过 PrintWindow 捕获窗口内容。"""
    if not win32gui or not win32ui or not _user32:
        return None
    hwnd_dc = mfc_dc = save_dc = save_bit_map = None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width < 8 or height < 8:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bit_map = win32ui.CreateBitmap()
        save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bit_map)

        ok = False
        for flag in (PW_RENDERFULLCONTENT, 0, 1):
            ok = bool(_user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flag))
            if ok:
                break
        if not ok:
            return None
        bgr = _bitmap_to_bgr(save_bit_map)
        return bgr if _is_valid_capture(bgr) else None
    except Exception as exc:
        print(f"[capture] PrintWindow failed: {exc}", flush=True)
        return None
    finally:
        try:
            if save_bit_map is not None:
                win32gui.DeleteObject(save_bit_map.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if hwnd_dc is not None and win32gui:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def capture_mss_region(monitor: dict) -> Optional[np.ndarray]:
    """按屏幕坐标截屏（会被叠在上面的窗口污染，仅作最后备选）。"""
    try:
        with mss.MSS() as sct:
            shot = sct.grab(monitor)
        rgb = np.array(Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception as exc:
        print(f"[capture] mss BitBlt failed: {exc}", flush=True)
        return None


def _hwnd_at_monitor_center(monitor: dict) -> Optional[int]:
    if not win32gui:
        return None
    cx = monitor["left"] + monitor["width"] // 2
    cy = monitor["top"] + monitor["height"] // 2
    try:
        return win32gui.WindowFromPoint((cx, cy))
    except Exception:
        return None


def _is_same_window_tree(target: int, candidate: int) -> bool:
    if not win32gui or not target or not candidate:
        return False
    if candidate == target:
        return True
    try:
        parent = win32gui.GetParent(candidate)
        depth = 0
        while parent and depth < 8:
            if parent == target:
                return True
            parent = win32gui.GetParent(parent)
            depth += 1
    except Exception:
        pass
    return False


def capture_bitblt_window_region(
    hwnd: int,
    x: int,
    y: int,
    width: int,
    height: int,
) -> Optional[np.ndarray]:
    """只截取窗口内指定区域（比全窗口截屏更省内存/更快）。"""
    if not win32gui or not win32ui or not win32con:
        return None
    if width < 4 or height < 4:
        return None
    hwnd_dc = mfc_dc = save_dc = save_bit_map = None
    try:
        wrect = win32gui.GetWindowRect(hwnd)
        ww, wh = wrect[2] - wrect[0], wrect[3] - wrect[1]
        x = max(0, min(x, ww - 4))
        y = max(0, min(y, wh - 4))
        width = min(width, ww - x)
        height = min(height, wh - y)
        if width < 4 or height < 4:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bit_map = win32ui.CreateBitmap()
        save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bit_map)
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (x, y), win32con.SRCCOPY)
        bgr = _bitmap_to_bgr(save_bit_map)
        return bgr if _is_valid_capture(bgr) else None
    except Exception as exc:
        print(f"[capture] BitBlt region failed: {exc}", flush=True)
        return None
    finally:
        try:
            if save_bit_map is not None:
                win32gui.DeleteObject(save_bit_map.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if hwnd_dc is not None and win32gui:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def capture_game_window_roi(
    hwnd: Optional[int],
    monitor: dict,
    roi: Tuple[int, int, int, int],
) -> Tuple[Optional[np.ndarray], str]:
    """优先截取框选区域；失败时回退全窗口。"""
    if hwnd:
        x1, y1, x2, y2 = roi
        w, h = x2 - x1, y2 - y1
        bgr = capture_bitblt_window_region(hwnd, x1, y1, w, h)
        if bgr is not None:
            return bgr, "BitBlt-ROI"
    bgr, method = capture_game_window(hwnd, monitor)
    if bgr is None:
        return None, method
    x1, y1, x2, y2 = roi
    fh, fw = bgr.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(fw, x2), min(fh, y2)
    if x2 > x1 and y2 > y1:
        return bgr[y1:y2, x1:x2].copy(), f"{method}-crop"
    return bgr, method


def capture_game_window(
    hwnd: Optional[int],
    monitor: dict,
) -> Tuple[Optional[np.ndarray], str]:
    """
    尝试多种截屏方式，返回 (bgr_image, method_name)。
    优先 BitBlt 窗口 DC，避免 mss 截到其他窗口（如浏览器）。
    """
    if hwnd:
        for method_name, capturer in (
            ("BitBlt", capture_bitblt_window),
            ("PrintWindow", capture_printwindow),
        ):
            bgr = capturer(hwnd)
            if bgr is not None:
                return bgr, method_name

    # mss 仅当目标窗口在最上层时才使用，否则返回空
    top_hwnd = _hwnd_at_monitor_center(monitor)
    if hwnd and top_hwnd and not _is_same_window_tree(hwnd, top_hwnd):
        top_title = ""
        try:
            top_title = win32gui.GetWindowText(top_hwnd) if win32gui else ""
        except Exception:
            pass
        print(
            f"[capture] Skip mss: another window '{top_title}' covers the game. "
            "Click the game window to bring it to front.",
            flush=True,
        )
        return None, "blocked"

    bgr = capture_mss_region(monitor)
    if bgr is not None:
        return bgr, "mss"
    return None, ""
