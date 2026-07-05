"""图像预处理：针对字幕、小字、图片内嵌文字、艺术字。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np


@dataclass
class PreprocessedFrame:
    name: str
    image: np.ndarray
    scale: float
    offset: Tuple[int, int]  # x, y in original coords
    region: str  # full | subtitle | dialog | small


def _ensure_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def _clahe_gray(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _sharpen(bgr: np.ndarray) -> np.ndarray:
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    return cv2.filter2D(bgr, -1, kernel)


def _upscale(bgr: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return bgr
    h, w = bgr.shape[:2]
    return cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _white_text_mask(bgr: np.ndarray) -> np.ndarray:
    """提取亮字（字幕常见：白/浅黄字 + 深色底）。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # 高亮度区域
    bright = cv2.inRange(hsv, (0, 0, 165), (180, 80, 255))
    gray = _clahe_gray(bgr)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_or(bright, th)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)


def _adaptive_text(bgr: np.ndarray) -> np.ndarray:
    gray = _clahe_gray(bgr)
    sharp = cv2.GaussianBlur(gray, (0, 0), 1.0)
    sharp = cv2.addWeighted(gray, 1.6, sharp, -0.6, 0)
    th = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


def _invert_if_dark_bg(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray)) < 110:
        return cv2.bitwise_not(bgr)
    return bgr


def _artistic_stroke_text(bgr: np.ndarray) -> np.ndarray:
    """艺术字 / 标题字：白描边 + 边缘 + 局部对比增强。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.8, tileGridSize=(4, 4))
    gray = clahe.apply(gray)
    _, white = cv2.threshold(gray, 168, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    _, thin = cv2.threshold(tophat, 12, 255, cv2.THRESH_BINARY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 35, 110)
    combined = cv2.bitwise_or(white, thin)
    combined = cv2.bitwise_or(combined, edges)
    combined = cv2.dilate(combined, np.ones((2, 2), np.uint8), iterations=1)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return cv2.cvtColor(combined, cv2.COLOR_GRAY2BGR)


def _green_button_text(bgr: np.ndarray) -> np.ndarray:
    """绿底白字按钮（底部导航等）：去绿底、保留白字。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (32, 35, 35), (92, 255, 255))
    not_green = cv2.bitwise_not(green)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, white = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
    text = cv2.bitwise_and(white, not_green)
    text = cv2.morphologyEx(text, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    return cv2.cvtColor(text, cv2.COLOR_GRAY2BGR)


def _saturated_text(bgr: np.ndarray) -> np.ndarray:
    """提取高饱和彩色 UI 字（粉/橙/黄，常见于游戏提示）。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    masks = [
        cv2.inRange(hsv, (0, 70, 100), (25, 255, 255)),
        cv2.inRange(hsv, (140, 60, 100), (180, 255, 255)),
        cv2.inRange(hsv, (20, 70, 120), (45, 255, 255)),
    ]
    mask = masks[0]
    for m in masks[1:]:
        mask = cv2.bitwise_or(mask, m)
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), iterations=1)
    out = cv2.bitwise_and(bgr, bgr, mask=mask)
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


def crop_region(bgr: np.ndarray, y0_ratio: float, y1_ratio: float, x0_ratio: float = 0.0, x1_ratio: float = 1.0) -> Tuple[np.ndarray, Tuple[int, int]]:
    h, w = bgr.shape[:2]
    y0, y1 = int(h * y0_ratio), int(h * y1_ratio)
    x0, x1 = int(w * x0_ratio), int(w * x1_ratio)
    return bgr[y0:y1, x0:x1].copy(), (x0, y0)


def build_preprocess_variants(bgr: np.ndarray, subtitle_boost: bool = True) -> List[PreprocessedFrame]:
    """生成多路预处理图像供 OCR 并行识别。"""
    bgr = _ensure_bgr(bgr)
    h, w = bgr.shape[:2]
    out: List[PreprocessedFrame] = []

    def add(name: str, img: np.ndarray, scale: float, offset: Tuple[int, int], region: str) -> None:
        out.append(PreprocessedFrame(name=name, image=img, scale=scale, offset=offset, region=region))

    # 1) 全屏标准增强
    base = _sharpen(bgr)
    add("full_std", base, 1.0, (0, 0), "full")

    # 2) 全屏 1.5x（小字）
    add("full_x1.5", _upscale(base, 1.5), 1.5, (0, 0), "full")

    # 3) 全屏 2x（极小字 / 艺术字）
    add("full_x2", _upscale(base, 2.0), 2.0, (0, 0), "small")

    # 4) 自适应二值化（图片内嵌字）
    add("full_adapt", _adaptive_text(_upscale(base, 1.5)), 1.5, (0, 0), "full")

    # 5) 反色 + 增强（深底 UI）
    inv = _invert_if_dark_bg(_upscale(base, 1.5))
    add("full_inv", inv, 1.5, (0, 0), "full")

    if subtitle_boost:
        # 6) 字幕带：底部 50%
        sub, (ox, oy) = crop_region(bgr, 0.50, 1.0, 0.02, 0.98)
        sub = _upscale(_sharpen(sub), 2.2)
        add("subtitle_x2.2", sub, 2.2, (ox, oy), "subtitle")

        # 7) 字幕：亮字提取
        sub2, (ox2, oy2) = crop_region(bgr, 0.48, 1.0, 0.0, 1.0)
        sub2 = _white_text_mask(_upscale(sub2, 2.5))
        add("subtitle_white_x2.5", sub2, 2.5, (ox2, oy2), "subtitle")

        # 8) 字幕：自适应阈值
        sub3, (ox3, oy3) = crop_region(bgr, 0.50, 0.99, 0.05, 0.95)
        sub3 = _adaptive_text(_upscale(sub3, 2.8))
        add("subtitle_adapt_x2.8", sub3, 2.8, (ox3, oy3), "subtitle")

        # 8b) 底部彩色大字（如「볼을 잡아당겨서 시작하기」）
        sub4, (ox4, oy4) = crop_region(bgr, 0.62, 0.96, 0.05, 0.95)
        sub4 = _upscale(_saturated_text(sub4), 3.0)
        add("subtitle_color_x3", sub4, 3.0, (ox4, oy4), "subtitle")

        # 8c) 底部中间提示区
        sub5, (ox5, oy5) = crop_region(bgr, 0.55, 0.92, 0.08, 0.92)
        sub5 = _upscale(_sharpen(sub5), 2.5)
        add("prompt_x2.5", sub5, 2.5, (ox5, oy5), "subtitle")

    # 9) 对话框区域：中部偏下
    dlg, (dx, dy) = crop_region(bgr, 0.35, 0.88, 0.08, 0.92)
    dlg = _upscale(_sharpen(dlg), 1.8)
    add("dialog_x1.8", dlg, 1.8, (dx, dy), "dialog")

    # 10) 顶部 UI（菜单/标题）
    top, (tx, ty) = crop_region(bgr, 0.0, 0.22, 0.0, 1.0)
    top = _upscale(_sharpen(top), 1.6)
    add("top_ui_x1.6", top, 1.6, (tx, ty), "full")

    return out
