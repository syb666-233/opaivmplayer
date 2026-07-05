# Trickcal: durable OCR region cache (physical screen pixels).
import copy
import time
from traceback import print_exc

import gobject
import windows
from myutils.config import globalconfig
from qtsymbols import *


def _log(msg: str) -> None:
    try:
        if gobject.base is None:
            return
        path = gobject.getconfig("trickcal_overlay.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [regions] {msg}\n")
    except Exception:
        pass


def copy_rect(rect):
    if not rect:
        return None
    (x1, y1), (x2, y2) = rect
    return ((int(x1), int(y1)), (int(x2), int(y2)))


def rect_key(rect) -> str:
    (x1, y1), (x2, y2) = copy_rect(rect) or ((0, 0), (0, 0))
    return f"{int(x1)},{int(y1)},{int(x2)},{int(y2)}"


def rect_center(rect) -> tuple[int, int]:
    (x1, y1), (x2, y2) = copy_rect(rect) or ((0, 0), (0, 0))
    return (int(x1 + x2) // 2, int(y1 + y2) // 2)


def rects_close(a, b, tol: int = 28) -> bool:
    a, b = copy_rect(a), copy_rect(b)
    if not a or not b:
        return False
    (ax1, ay1), (ax2, ay2) = a
    (bx1, by1), (bx2, by2) = b
    return (
        abs(ax1 - bx1) <= tol
        and abs(ay1 - by1) <= tol
        and abs(ax2 - bx2) <= tol
        and abs(ay2 - by2) <= tol
    )


def rect_overlap_ratio(a, b) -> float:
    a, b = copy_rect(a), copy_rect(b)
    if not a or not b:
        return 0.0
    (ax1, ay1), (ax2, ay2) = a
    (bx1, by1), (bx2, by2) = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / float(min(area_a, area_b))


def remove_region_by_rect(rect) -> bool:
    """Drop cached metadata for one OCR region (keep other regions)."""
    if gobject.base is None:
        return False
    rect = copy_rect(rect)
    if not rect:
        return False
    base = gobject.base
    m = getattr(base, "trickcal_source_rect_map", None) or {}
    for key in list(m.keys()):
        if rects_close(m.get(key), rect):
            del m[key]
    base.trickcal_source_rect_map = m
    pending = getattr(base, "trickcal_pending_translate", None)
    if pending and rects_close(pending.get("rect"), rect):
        base.trickcal_pending_translate = None
    base.trickcal_ocr_regions = [
        it
        for it in (getattr(base, "trickcal_ocr_regions", None) or [])
        if not rects_close(it.get("rect"), rect)
    ]
    base.trickcal_region_cache = [
        it
        for it in (getattr(base, "trickcal_region_cache", None) or [])
        if not rects_close(it.get("rect"), rect)
    ]
    offsets = globalconfig.get("trickcal_overlay_offsets") or {}
    rk = rect_key(rect)
    changed = False
    for ok in list(offsets.keys()):
        if ok == rk or rects_close(_parse_rect_key(ok), rect):
            offsets.pop(ok, None)
            changed = True
    if changed:
        try:
            from myutils.config import saveallconfig

            saveallconfig()
        except Exception:
            pass
    _log(f"remove_region {rect}")
    return True


def _parse_rect_key(key: str):
    try:
        parts = [int(x) for x in (key or "").split(",")]
        if len(parts) == 4:
            return ((parts[0], parts[1]), (parts[2], parts[3]))
    except Exception:
        pass
    return None


def remember_crop_screen(x1, y1, x2, y2) -> None:
    """Called from imageCut — record crop coords only (do not clobber multi-region cache)."""
    if gobject.base is None:
        return
    x1, x2 = int(min(x1, x2)), int(max(x1, x2))
    y1, y2 = int(min(y1, y2)), int(max(y1, y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return
    rect = ((x1, y1), (x2, y2))
    base = gobject.base
    base.trickcal_last_crop_rect = rect
    base.trickcal_last_crop_time = time.time()
    _log(f"crop_screen {rect}")


def on_ocr_result(result) -> None:
    """Called from ocr_run after OCR — attach text to last crop rect."""
    if gobject.base is None or result is None:
        return
    try:
        text = (result.textonly or "").strip()
    except Exception:
        text = ""
    if not text:
        return
    base = gobject.base
    mode = getattr(base, "trickcal_crop_mode", None)
    once = getattr(base, "trickcal_once_active", False)
    rect = getattr(base, "trickcal_once_rect", None) or getattr(
        base, "trickcal_last_crop_rect", None
    )
    if (mode == "once" or once) and rect:
        remember_for_translate(rect, text)
        return
    if rect:
        _log(f"ocr_text {rect} {text[:24]!r}")


def clear_all() -> None:
    if gobject.base is None:
        return
    base = gobject.base
    base.trickcal_region_cache = []
    base.trickcal_region_cache_time = 0
    base.trickcal_ocr_regions = []
    base.trickcal_source_rect_map = {}
    base.trickcal_pending_translate = None
    base.trickcal_last_crop_rect = None
    base.trickcal_last_crop_time = 0
    base.trickcal_crop_mode = None
    base.trickcal_once_rect = None
    base.trickcal_once_active = False
    _log("clear_all region cache")


def rect_from_range_ui(range_ui):
    if range_ui is None:
        return None
    rect = range_ui.getrect()
    if rect:
        return copy_rect(rect)
    try:
        wid = int(range_ui.winId())
        if wid:
            wr = windows.GetWindowRect(wid)
            w, h = wr[2] - wr[0], wr[3] - wr[1]
            if w > 2 and h > 2:
                geo = QRect(wr[0], wr[1], w, h)
                inner = range_ui.rectoffset(geo)
                if inner:
                    return copy_rect(inner)
                return ((wr[0], wr[1]), (wr[2], wr[3]))
    except Exception:
        print_exc()
    return None


def remember_for_translate(rect, source_text: str) -> None:
    """Pin the next translation overlay to this OCR source + rect."""
    if gobject.base is None:
        return
    source_text = (source_text or "").strip()
    rect = copy_rect(rect)
    if not rect or not source_text:
        return
    remember_rect(rect, text=source_text)
    base = gobject.base
    m = getattr(base, "trickcal_source_rect_map", None) or {}
    m[source_text] = rect
    base.trickcal_source_rect_map = m
    base.trickcal_pending_translate = {
        "source": source_text,
        "rect": rect,
        "time": time.time(),
    }
    _log(f"for_translate {rect} src={source_text[:24]!r}")


def resolve_region_for_source(source: str):
    source = (source or "").strip()
    if not source or gobject.base is None:
        return None
    pending = getattr(gobject.base, "trickcal_pending_translate", None)
    if pending and pending.get("source") == source and pending.get("rect"):
        return {"rect": copy_rect(pending["rect"]), "text": source}
    m = getattr(gobject.base, "trickcal_source_rect_map", None) or {}
    rect = m.get(source)
    if rect:
        return {"rect": copy_rect(rect), "text": source}
    return None


def get_regions_for_overlay(source: str = "") -> list[dict]:
    hit = resolve_region_for_source(source)
    if hit:
        return [hit]
    return get_regions()


def remember_rect(rect, text: str = "", source: str = "") -> None:
    if gobject.base is None:
        return
    rect = copy_rect(rect)
    if not rect:
        return
    (x1, y1), (x2, y2) = rect
    if abs(x2 - x1) < 4 or abs(y2 - y1) < 4:
        return
    item = {"rect": rect, "text": (text or "").strip()}
    base = gobject.base
    base.trickcal_region_cache = [item]
    base.trickcal_region_cache_time = time.time()
    if source:
        base.trickcal_region_cache_source = source.strip()
    base.trickcal_ocr_regions = [copy.deepcopy(item)]
    _log(f"remember_rect {rect} text={item['text'][:24]!r}")


def remember_items(items: list[dict], source: str = "") -> None:
    valid = []
    for it in items or []:
        rect = copy_rect(it.get("rect"))
        if not rect:
            continue
        valid.append({"rect": rect, "text": (it.get("text") or "").strip()})
    if not valid:
        return
    base = gobject.base
    base.trickcal_region_cache = copy.deepcopy(valid)
    base.trickcal_region_cache_time = time.time()
    if source:
        base.trickcal_region_cache_source = source.strip()
    base.trickcal_ocr_regions = copy.deepcopy(valid)
    _log(f"remember_items count={len(valid)} source={source[:24]!r}")


def remember_multi_regions(pairs) -> None:
    """Store all active OCR rects without pinning the next translation to all of them."""
    items = []
    for rm, res in pairs or []:
        rect = getattr(rm, "trickcal_crop_rect", None) or rect_from_range_ui(rm.range_ui)
        text = ""
        try:
            text = res.textonly or ""
        except Exception:
            pass
        if rect:
            items.append({"rect": copy_rect(rect), "text": text.strip()})
    if not items or gobject.base is None:
        return
    gobject.base.trickcal_ocr_regions = copy.deepcopy(items)
    _log(f"multi_regions count={len(items)}")


def remember_from_pairs(pairs, source: str = "") -> None:
    items = []
    for rm, res in pairs or []:
        rect = getattr(rm, "trickcal_crop_rect", None) or rect_from_range_ui(rm.range_ui)
        text = ""
        try:
            text = res.textonly or ""
        except Exception:
            pass
        if rect:
            items.append({"rect": copy_rect(rect), "text": text.strip()})
    remember_items(items, source=source)


def remember_from_textsource(source: str = "") -> bool:
    ts = getattr(gobject.base, "textsource", None)
    if not ts or not hasattr(ts, "ranges"):
        return False
    items = []
    for rm in ts.ranges:
        rect = getattr(rm, "trickcal_crop_rect", None) or rect_from_range_ui(rm.range_ui)
        if not rect:
            continue
        items.append(
            {
                "rect": copy_rect(rect),
                "text": (getattr(rm, "savelasttext", None) or source or "").strip(),
            }
        )
    if items:
        remember_items(items, source=source)
        return True
    return False


def remember_from_config() -> bool:
    items = []
    for reg in globalconfig.get("ocrregions") or []:
        rect = copy_rect(reg)
        if rect:
            items.append({"rect": rect, "text": ""})
    if items:
        remember_items(items)
        return True
    return False


def remember_from_follow_rect() -> bool:
    try:
        ui = getattr(gobject.base, "translation_ui", None)
        if ui is None:
            return False
        rect = getattr(ui, "ocr_once_follow_rect", None)
        if rect:
            remember_rect(rect)
            return True
    except Exception:
        print_exc()
    return False


def get_regions(max_age_sec: float = 300.0) -> list[dict]:
    if gobject.base is None:
        return []
    base = gobject.base
    now = time.time()
    cache = getattr(base, "trickcal_region_cache", None) or []
    ts = getattr(base, "trickcal_region_cache_time", 0) or 0
    if cache and (now - ts) <= max_age_sec:
        out = [it for it in cache if it.get("rect")]
        if out:
            return out
    last = getattr(base, "trickcal_last_crop_rect", None)
    last_t = getattr(base, "trickcal_last_crop_time", 0) or 0
    if last and (now - last_t) <= max_age_sec:
        return [{"rect": copy_rect(last), "text": ""}]
    stored = getattr(base, "trickcal_ocr_regions", None) or []
    out = [it for it in stored if it.get("rect")]
    if out:
        return out
    if remember_from_follow_rect():
        return getattr(base, "trickcal_region_cache", []) or []
    if remember_from_textsource():
        return getattr(base, "trickcal_region_cache", []) or []
    remember_from_config()
    return getattr(base, "trickcal_region_cache", []) or []


def tag_crop(rm, rect, text: str = "") -> None:
    rect = copy_rect(rect)
    if not rect or rm is None:
        return
    rm.trickcal_crop_rect = rect
    if text:
        rm.savelasttext = text
