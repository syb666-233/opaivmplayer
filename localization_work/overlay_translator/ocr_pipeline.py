"""多引擎 OCR + 结果合并（韩文 / 字幕 / 小字）。"""
from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ocr_preprocess import PreprocessedFrame, build_preprocess_variants

# 降低 Paddle oneDNN 在 Py3.13 上的崩溃概率
os.environ.setdefault("FLAGS_use_mkldnn", "0")

OCR_MAX_WIDTH = 960  # OCR 输入最大宽度，减小可显著提速
OCR_FULL_PREVIEW_WIDTH = 960  # 全屏兜底扫描宽度（GPU）
# EasyOCR 检测灵敏度：游戏 UI 字细/描边多，默认阈值会漏检
EASYOCR_READ_KW = {
    "paragraph": False,
    "text_threshold": 0.55,
    "low_text": 0.28,
    "link_threshold": 0.32,
    "width_ths": 0.55,
    "mag_ratio": 1.5,
}
# 框选 / 艺术字：更高放大、更低阈值
EASYOCR_ROI_KW = {
    "paragraph": False,
    "text_threshold": 0.42,
    "low_text": 0.20,
    "link_threshold": 0.28,
    "width_ths": 0.45,
    "mag_ratio": 2.2,
}
# 弹窗 / 多行说明：启用 paragraph 模式，降低漏检
EASYOCR_PARAGRAPH_KW = {
    "paragraph": True,
    "text_threshold": 0.35,
    "low_text": 0.15,
    "link_threshold": 0.24,
    "width_ths": 0.38,
    "mag_ratio": 2.6,
}

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

try:
    import easyocr
except ImportError:
    easyocr = None


@dataclass
class OcrHit:
    text: str
    bbox: Tuple[int, int, int, int]
    confidence: float
    region: str
    source: str


HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")
JAMO_RE = re.compile(r"[\u3131-\u318E]")


def _hangul_ratio(text: str) -> float:
    if not text:
        return 0.0
    hangul = sum(1 for c in text if HANGUL_RE.match(c))
    jamo = sum(1 for c in text if JAMO_RE.match(c))
    return (hangul + jamo * 0.5) / max(len(text), 1)


def _clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_valid_korean_text(text: str, min_hangul: int = 1, region: str = "") -> bool:
    text = _clean_text(text)
    if len(text) < 1:
        return False
    hangul_count = sum(1 for c in text if HANGUL_RE.match(c))
    if hangul_count < min_hangul:
        return False
    # UI 短标签（商店/卡牌等）常为 2~4 个韩字
    if region in ("ui", "full", "dialog") and hangul_count >= 1 and len(text) <= 6:
        if hangul_count / max(len(text), 1) >= 0.5:
            return True
    if _hangul_ratio(text) < 0.25 and hangul_count < 2:
        return False
    if len(text) <= 2 and hangul_count == 1 and not text.isalpha():
        return False
    return True


def _map_bbox(bbox_pts, scale: float, offset: Tuple[int, int]) -> Tuple[int, int, int, int]:
    ox, oy = offset
    xs = [p[0] / scale + ox for p in bbox_pts]
    ys = [p[1] / scale + oy for p in bbox_pts]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def _bbox_width(b: Tuple[int, int, int, int]) -> int:
    return max(0, b[2] - b[0])


def _bbox_height(b: Tuple[int, int, int, int]) -> int:
    return max(0, b[3] - b[1])


def _bbox_center(b: Tuple[int, int, int, int]) -> Tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _text_similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def assemble_roi_text(hits: List[OcrHit]) -> str:
    """将 ROI 内多段 OCR 按行拼接为可读原文。"""
    lines = _group_hits_into_lines(hits)
    if not lines:
        return ""
    parts: List[str] = []
    for line in lines:
        line.sort(key=lambda h: h.bbox[0])
        text = " ".join(h.text.strip() for h in line if h.text.strip())
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _group_hits_into_lines(hits: List[OcrHit], *, y_ratio: float = 0.32) -> List[List[OcrHit]]:
    """按 y 坐标将 OCR 片段分组为多行。"""
    if not hits:
        return []
    hits = sorted(hits, key=lambda h: (h.bbox[1], h.bbox[0]))
    lines: List[List[OcrHit]] = []
    for hit in hits:
        placed = False
        for line in lines:
            ref = line[0]
            y_overlap = min(ref.bbox[3], hit.bbox[3]) - max(ref.bbox[1], hit.bbox[1])
            min_h = max(1, min(_bbox_height(ref.bbox), _bbox_height(hit.bbox)))
            if y_overlap >= min_h * y_ratio:
                line.append(hit)
                placed = True
                break
        if not placed:
            lines.append([hit])
    return lines


def infer_paragraph_from_hits(hits: List[OcrHit], ch: int, cw: int) -> bool:
    """根据 OCR 结果推断是否为多行段落（即使选区较矮）。"""
    if ch < 36 or cw < 90:
        return False
    lines = _group_hits_into_lines(hits)
    meaningful = [
        ln for ln in lines
        if sum(len(h.text.strip()) for h in ln) >= 3
    ]
    return len(meaningful) >= 2


def filter_roi_hits(
    hits: List[OcrHit],
    roi: Tuple[int, int, int, int],
    *,
    compact: bool,
) -> List[OcrHit]:
    """窄选区时只保留最靠近中心的高置信度结果，避免误并相邻按钮。"""
    if not hits:
        return hits
    if not compact or len(hits) <= 1:
        return hits
    rcx = (roi[0] + roi[2]) / 2
    rcy = (roi[1] + roi[3]) / 2

    def score(h: OcrHit) -> float:
        cx, cy = _bbox_center(h.bbox)
        dist = ((cx - rcx) ** 2 + (cy - rcy) ** 2) ** 0.5
        return h.confidence * (1 + len(h.text) * 0.08) / (1 + dist / 40)

    best = max(hits, key=score)
    return [best]


def pick_single_roi_source(
    hits: List[OcrHit],
    roi: Tuple[int, int, int, int],
) -> str:
    """框选模式：优先底部同一行文字合并（保留「캐시 상점」等双词标签）。"""
    if not hits:
        return ""

    y0, y1 = roi[1], roi[3]
    y_split = y0 + (y1 - y0) * 0.38
    bottom = [h for h in hits if _bbox_center(h.bbox)[1] >= y_split]
    work = bottom if bottom else hits

    # 按行分组
    work = sorted(work, key=lambda h: (h.bbox[1], h.bbox[0]))
    lines: List[List[OcrHit]] = []
    for hit in work:
        placed = False
        for line in lines:
            ref = line[0]
            y_overlap = min(ref.bbox[3], hit.bbox[3]) - max(ref.bbox[1], hit.bbox[1])
            min_h = max(1, min(_bbox_height(ref.bbox), _bbox_height(hit.bbox)))
            if y_overlap >= min_h * 0.40:
                line.append(hit)
                placed = True
                break
        if not placed:
            lines.append([hit])

    if not lines:
        return ""

    rcx = (roi[0] + roi[2]) / 2
    rcy = (roi[1] + roi[3]) / 2

    def line_score(line: List[OcrHit]) -> float:
        line.sort(key=lambda h: h.bbox[0])
        text_len = sum(len(h.text) for h in line)
        conf = sum(h.confidence for h in line) / max(len(line), 1)
        cx = sum(_bbox_center(h.bbox)[0] for h in line) / len(line)
        cy = sum(_bbox_center(h.bbox)[1] for h in line) / len(line)
        dist = ((cx - rcx) ** 2 + (cy - rcy) ** 2) ** 0.5
        lower_bonus = 1.2 if cy >= y_split else 1.0
        return conf * (1 + text_len * 0.05) * lower_bonus / (1 + dist / 40)

    best_line = max(lines, key=line_score)
    best_line.sort(key=lambda h: h.bbox[0])
    merged = " ".join(h.text.strip() for h in best_line if h.text.strip())
    if merged:
        return merged

    # 兜底：窄选区只保留中心最近一条
    narrow = (roi[2] - roi[0]) < 130 or (roi[3] - roi[1]) < 70
    if narrow and len(work) > 1:
        work = filter_roi_hits(work, roi, compact=True)
    if len(work) == 1:
        return work[0].text.strip()
    return max(work, key=lambda h: h.confidence * len(h.text)).text.strip()


def _compact_text(text: str) -> str:
    import re
    return re.sub(r"\s+", "", (text or "").strip())


def roi_is_paragraph(ch: int, cw: int) -> bool:
    """弹窗、说明框等多行区域（相对宽按钮标签）。"""
    return ch >= 50 or (ch >= 38 and cw >= 130) or (ch >= 70 and cw >= 90)


def compact_join_bottom_line(
    hits: List[OcrHit],
    roi: Tuple[int, int, int, int],
) -> str:
    """宽菜单按钮：按 x 序合并底部同一行 OCR 片段（如 캐시 + 상점）。"""
    if not hits:
        return ""
    y0, y1 = roi[1], roi[3]
    y_split = y0 + (y1 - y0) * 0.35
    bottom = [h for h in hits if _bbox_center(h.bbox)[1] >= y_split]
    work = bottom if bottom else hits
    work = sorted(work, key=lambda h: h.bbox[0])
    return " ".join(h.text.strip() for h in work if h.text.strip())


def pick_roi_source(
    hits: List[OcrHit],
    roi: Tuple[int, int, int, int],
    ch: int,
    cw: int,
) -> Tuple[str, bool]:
    """框选 OCR 原文：单行 UI 标签 vs 多行段落。"""
    is_para = roi_is_paragraph(ch, cw) or infer_paragraph_from_hits(hits, ch, cw)
    if is_para:
        return assemble_roi_text(hits), True

    single = pick_single_roi_source(hits, roi)
    is_wide_btn = cw >= 110 and ch < 140
    if is_wide_btn:
        wide = compact_join_bottom_line(hits, roi)
        if wide and len(_compact_text(wide)) >= len(_compact_text(single)) + 2:
            return wide, False
    return single, False


def _release_gpu_cache() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _paddle_cuda_available() -> bool:
    try:
        import paddle
        return bool(paddle.is_compiled_with_cuda())
    except Exception:
        return False


def _setup_paddle_dll_directories() -> None:
    """Windows：让 Paddle GPU 找到 pip 安装的 nvidia/cu11 DLL（须在 import paddle 前调用）。"""
    import sys
    from pathlib import Path

    sp = Path(sys.executable).resolve().parent / "Lib" / "site-packages" / "nvidia"
    if not sp.is_dir():
        return
    add = getattr(os, "add_dll_directory", None)
    if not add:
        return
    for pkg in sorted(sp.iterdir()):
        bin_dir = pkg / "bin"
        if bin_dir.is_dir():
            try:
                add(str(bin_dir))
            except OSError:
                pass


def _paddle_gpu_usable() -> bool:
    if not _paddle_cuda_available():
        return False
    try:
        _setup_paddle_dll_directories()
        import paddle
        probe = paddle.to_tensor([1.0], dtype="float32")
        probe = probe.cuda()
        return bool(getattr(probe.place, "is_gpu_place", lambda: True)())
    except Exception as exc:
        print(f"[ocr] Paddle GPU probe failed: {exc}", flush=True)
        return False


def _paddle_init_kwargs(device: str) -> dict:
    """游戏截图 OCR：关闭文档矫正，减少模型加载与推理耗时。"""
    return {
        "lang": "korean",
        "enable_mkldnn": False,
        "device": device,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }


def _resize_for_ocr(img: np.ndarray, max_width: int = OCR_MAX_WIDTH) -> Tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    if w <= max_width:
        return img, 1.0
    scale = max_width / w
    resized = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


class KoreanOcrPipeline:
    def __init__(self, fast_mode: bool = True, coverage_boost: bool = True) -> None:
        self._paddle = None
        self._rapid = None
        self._easyocr = None
        self._use_gpu = False
        self._paddle_gpu = False
        self._device_label = "CPU"
        self._fast_mode = fast_mode
        self._coverage_boost = coverage_boost
        self._infer_lock = threading.Lock()
        self._init_engines()

    @property
    def primary_ocr(self) -> str:
        return "paddle" if self._paddle else ("easyocr" if self._easyocr else "none")

    @property
    def paddle_gpu(self) -> bool:
        return self._paddle_gpu

    def _paddle_warmup(self, ocr) -> bool:
        """Paddle 3.x 在 Py3.13 上可能加载成功但推理崩溃，需预热验证。"""
        try:
            probe = np.full((64, 128, 3), 255, dtype=np.uint8)
            if hasattr(ocr, "predict"):
                list(ocr.predict(probe))
            else:
                ocr.ocr(probe)
            return True
        except Exception as exc:
            print(f"[ocr] PaddleOCR warmup failed (disabled): {exc}", flush=True)
            return False

    def _init_engines(self) -> None:
        use_gpu = False
        try:
            import torch
            use_gpu = bool(torch.cuda.is_available())
            if use_gpu:
                self._device_label = torch.cuda.get_device_name(0)
                torch.set_num_threads(2)
            else:
                ver = getattr(torch, "__version__", "")
                if "+cpu" in ver:
                    print(
                        "[ocr] PyTorch CPU 版 (无 CUDA)。有 NVIDIA 显卡请运行 install_gpu_torch.bat",
                        flush=True,
                    )
                torch.set_num_threads(2)
        except Exception:
            pass
        self._use_gpu = use_gpu

        paddle_device = "cpu"
        if use_gpu and _paddle_gpu_usable():
            paddle_device = "gpu:0"
            self._paddle_gpu = True
        elif use_gpu and _paddle_cuda_available():
            print(
                "[ocr] Paddle GPU 库加载失败（多为 cu12/cu11 混装）。"
                "请运行 install_paddle_gpu.bat 修复",
                flush=True,
            )
        elif use_gpu:
            print(
                "[ocr] 当前 paddlepaddle 为 CPU 版。运行 install_paddle_gpu.bat 可启用 Paddle GPU",
                flush=True,
            )

        if PaddleOCR is not None:
            _setup_paddle_dll_directories()
            for extra in ({}, {"ocr_version": "PP-OCRv4"}):
                kwargs = {**_paddle_init_kwargs(paddle_device), **extra}
                try:
                    mode = "GPU" if self._paddle_gpu else "CPU"
                    print(f"[ocr] Loading PaddleOCR (Korean, {mode}, 主引擎)...", flush=True)
                    candidate = PaddleOCR(**kwargs)
                    if self._paddle_warmup(candidate):
                        self._paddle = candidate
                        print(f"[ocr] PaddleOCR ready ({mode}).", flush=True)
                        break
                except Exception as exc:
                    print(f"[ocr] PaddleOCR attempt failed: {exc}", flush=True)
                    self._paddle = None

        # EasyOCR 作为 Paddle 失败或置信度不足时的备用
        if easyocr is not None:
            try:
                from download_models import models_ready, model_dir

                if not models_ready():
                    print(
                        "[ocr] EasyOCR models missing. Run download_models.bat first.",
                        flush=True,
                    )
                mode = "GPU" if use_gpu else "CPU"
                print(f"[ocr] Loading EasyOCR (Korean, {mode}, 备用)...", flush=True)
                self._easyocr = easyocr.Reader(
                    ["ko"],
                    gpu=use_gpu,
                    verbose=False,
                    model_storage_directory=str(model_dir()),
                    download_enabled=not models_ready(),
                )
                print(f"[ocr] EasyOCR ready ({mode}).", flush=True)
            except Exception as exc:
                print(f"[ocr] EasyOCR failed: {exc}", flush=True)
                self._easyocr = None

        if RapidOCR is not None and self._paddle is None and self._easyocr is None:
            try:
                print("[ocr] Loading RapidOCR...", flush=True)
                self._rapid = RapidOCR()
                print("[ocr] RapidOCR ready.", flush=True)
            except Exception as exc:
                print(f"[ocr] RapidOCR failed: {exc}", flush=True)
                self._rapid = None

        if self._easyocr is not None:
            pass  # torch threads already set above

    @property
    def device_label(self) -> str:
        return self._device_label

    @property
    def use_gpu(self) -> bool:
        return self._use_gpu

    @property
    def ready(self) -> bool:
        return self._paddle is not None or self._easyocr is not None or self._rapid is not None

    def _parse_paddle_result(self, res) -> List[Tuple[list, str, float]]:
        out: List[Tuple[list, str, float]] = []
        if not res:
            return out
        # PaddleOCR 2.x: [[[bbox], (text, conf)], ...]
        if isinstance(res, list) and res and isinstance(res[0], list):
            for line in res[0] or []:
                if not line or len(line) < 2:
                    continue
                bbox, pair = line[0], line[1]
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    out.append((bbox, str(pair[0]), float(pair[1])))
            return out
        # PaddleOCR 3.x / PaddleX: dict with rec_texts / rec_scores
        for item in res if isinstance(res, list) else [res]:
            if not isinstance(item, dict):
                continue
            texts = item.get("rec_texts") or item.get("texts") or []
            scores = item.get("rec_scores") or item.get("scores") or []
            polys = item.get("dt_polys") or item.get("rec_polys") or item.get("polys") or []
            for i, text in enumerate(texts):
                conf = float(scores[i]) if i < len(scores) else 0.5
                bbox = polys[i] if i < len(polys) else [[0, 0], [1, 0], [1, 1], [0, 1]]
                out.append((bbox, str(text), conf))
        return out

    def _run_paddle(self, img: np.ndarray) -> List[Tuple[list, str, float]]:
        if not self._paddle:
            return []
        try:
            if hasattr(self._paddle, "predict"):
                res = list(self._paddle.predict(img))
            else:
                res = self._paddle.ocr(img)
            return self._parse_paddle_result(res)
        except Exception as exc:
            print(f"[ocr] Paddle infer error: {exc}", flush=True)
            return []

    def _run_easyocr(
        self,
        img: np.ndarray,
        *,
        read_kw: Optional[dict] = None,
        max_width: int = OCR_MAX_WIDTH,
    ) -> List[Tuple[list, str, float]]:
        if not self._easyocr:
            return []
        try:
            import torch
            ctx = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad
            with self._infer_lock:
                with ctx():
                    small, ocr_scale = _resize_for_ocr(img, max_width)
                    kw = read_kw or EASYOCR_READ_KW
                    results = self._easyocr.readtext(small, **kw)
        except Exception:
            return []
        out = []
        inv = 1.0 / max(ocr_scale, 1e-6)
        for item in results or []:
            if len(item) < 3:
                continue
            bbox, text, conf = item[0], item[1], float(item[2])
            scaled = [[p[0] * inv, p[1] * inv] for p in bbox]
            out.append((scaled, str(text), conf))
        return out

    def _run_rapid(self, img: np.ndarray) -> List[Tuple[list, str, float]]:
        if not self._rapid:
            return []
        try:
            result, _ = self._rapid(img)
        except Exception:
            return []
        if not result:
            return []
        out = []
        for item in result:
            if len(item) < 3:
                continue
            out.append((item[0], item[1], float(item[2])))
        return out

    def _min_confidence(self, region: str, engine: str = "", *, roi: bool = False) -> float:
        if engine == "easyocr":
            if roi:
                return 0.06
            if region in ("subtitle", "dialog"):
                return 0.10
            if region == "ui":
                return 0.09
            if region == "small":
                return 0.12
            return 0.10
        if engine == "paddle":
            if roi:
                return 0.25
            if region in ("subtitle", "dialog"):
                return 0.30
            return 0.35
        if region == "subtitle":
            return 0.28
        if region == "small":
            return 0.32
        if region == "dialog":
            return 0.35
        return 0.38

    def _hits_from_easyocr_image(
        self,
        img: np.ndarray,
        scale: float,
        offset: Tuple[int, int],
        region: str,
        tag: str,
        *,
        read_kw: Optional[dict] = None,
        min_conf: Optional[float] = None,
        max_width: int = OCR_MAX_WIDTH,
    ) -> List[OcrHit]:
        hits: List[OcrHit] = []
        floor = min_conf if min_conf is not None else self._min_confidence(region, "easyocr")
        for bbox, text, conf in self._run_easyocr(img, read_kw=read_kw, max_width=max_width):
            text = _clean_text(text)
            if conf < floor or not _is_valid_korean_text(text, region=region):
                continue
            hits.append(
                OcrHit(
                    text=text,
                    bbox=_map_bbox(bbox, scale, offset),
                    confidence=conf,
                    region=region,
                    source=f"easyocr:{tag}",
                )
            )
        return hits

    def _hits_from_paddle_image(
        self,
        img: np.ndarray,
        scale: float,
        offset: Tuple[int, int],
        region: str,
        tag: str,
        *,
        min_conf: Optional[float] = None,
    ) -> List[OcrHit]:
        if not self._paddle:
            return []
        hits: List[OcrHit] = []
        floor = min_conf if min_conf is not None else self._min_confidence(region, "paddle", roi=True)
        with self._infer_lock:
            for bbox, text, conf in self._run_paddle(img):
                text = _clean_text(text)
                if conf < floor or not _is_valid_korean_text(text, region=region):
                    continue
                hits.append(
                    OcrHit(
                        text=text,
                        bbox=_map_bbox(bbox, scale, offset),
                        confidence=conf,
                        region=region,
                        source=f"paddle:{tag}",
                    )
                )
        return hits

    def _ocr_variant(self, frame: PreprocessedFrame) -> List[OcrHit]:
        img = frame.image
        img, ocr_scale = _resize_for_ocr(img)
        combined_scale = frame.scale * ocr_scale
        hits: List[OcrHit] = []
        engines: List[Tuple[str, callable]] = []
        if self._paddle:
            engines.append(("paddle", self._run_paddle))
        if self._easyocr:
            engines.append(("easyocr", self._run_easyocr))
        if self._rapid and not self._paddle and not self._easyocr:
            engines.append(("rapid", self._run_rapid))
        for eng_name, runner in engines:
            min_conf = self._min_confidence(frame.region, eng_name)
            for bbox, text, conf in runner(img):
                text = _clean_text(text)
                if conf < min_conf:
                    continue
                if not _is_valid_korean_text(text, region=frame.region):
                    continue
                bb = _map_bbox(bbox, combined_scale, frame.offset)
                hits.append(
                    OcrHit(
                        text=text,
                        bbox=bb,
                        confidence=conf,
                        region=frame.region,
                        source=f"{eng_name}:{frame.name}",
                    )
                )
        return hits

    def _merge_hits(self, hits: List[OcrHit], frame_size: Optional[Tuple[int, int]] = None) -> List[OcrHit]:
        if not hits:
            return []
        frame_w = frame_size[0] if frame_size else 9999
        hits = sorted(hits, key=lambda h: (-h.confidence, -len(h.text)))
        merged: List[OcrHit] = []

        # 第一步：去重（相似文本保留置信度最高者，不扩大 bbox）
        for hit in hits:
            duplicate = False
            for m in merged:
                sim = _text_similar(hit.text, m.text)
                iou = _iou(hit.bbox, m.bbox)
                if sim >= 0.88 or (sim >= 0.72 and iou >= 0.35):
                    duplicate = True
                    if hit.confidence > m.confidence:
                        m.text = hit.text if len(hit.text) >= len(m.text) else m.text
                        m.confidence = hit.confidence
                        m.bbox = hit.bbox
                    break
            if not duplicate:
                merged.append(
                    OcrHit(
                        text=hit.text,
                        bbox=hit.bbox,
                        confidence=hit.confidence,
                        region=hit.region,
                        source=hit.source,
                    )
                )

        # 第二步：仅合并底部字幕的同一行相邻片段（UI 按钮禁止合并）
        merged.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
        line_merged: List[OcrHit] = []
        for hit in merged:
            if hit.region != "subtitle":
                line_merged.append(hit)
                continue
            attached = False
            for m in line_merged:
                if m.region != "subtitle":
                    continue
                y_overlap = min(m.bbox[3], hit.bbox[3]) - max(m.bbox[1], hit.bbox[1])
                min_h = min(_bbox_height(m.bbox), _bbox_height(hit.bbox), 1)
                if y_overlap < min_h * 0.45:
                    continue
                gap = hit.bbox[0] - m.bbox[2]
                if gap < 0 or gap > 28:
                    continue
                # 合并后宽度不应超过半屏（避免 UI 误并）
                new_w = max(m.bbox[2], hit.bbox[2]) - min(m.bbox[0], hit.bbox[0])
                if frame_w < 9999 and new_w > frame_w * 0.55:
                    continue
                m.text = _clean_text(m.text + " " + hit.text)
                m.bbox = (
                    min(m.bbox[0], hit.bbox[0]),
                    min(m.bbox[1], hit.bbox[1]),
                    max(m.bbox[2], hit.bbox[2]),
                    max(m.bbox[3], hit.bbox[3]),
                )
                m.confidence = max(m.confidence, hit.confidence)
                attached = True
                break
            if not attached:
                line_merged.append(hit)

        # 过滤过宽误检（subtitle 区易把多按钮并成一行；任务横幅等宽文本需保留）
        filtered: List[OcrHit] = []
        for h in line_merged:
            if frame_w < 9999 and h.region == "subtitle":
                if _bbox_width(h.bbox) > frame_w * 0.62:
                    continue
            filtered.append(h)

        order = {"subtitle": 0, "dialog": 1, "small": 2, "full": 3}
        filtered.sort(key=lambda h: (order.get(h.region, 9), h.bbox[1], h.bbox[0]))
        return filtered

    def _merge_hits_paragraph(self, hits: List[OcrHit]) -> List[OcrHit]:
        """段落模式：保留各行，仅去重完全相同/同位置片段。"""
        if not hits:
            return []
        hits = sorted(hits, key=lambda h: (-h.confidence, -len(h.text)))
        merged: List[OcrHit] = []
        for hit in hits:
            duplicate = False
            for m in merged:
                sim = _text_similar(hit.text, m.text)
                iou = _iou(hit.bbox, m.bbox)
                if sim >= 0.96 or (sim >= 0.82 and iou >= 0.45):
                    duplicate = True
                    if len(hit.text) > len(m.text) or hit.confidence > m.confidence:
                        m.text = hit.text if len(hit.text) >= len(m.text) else m.text
                        m.confidence = max(m.confidence, hit.confidence)
                        m.bbox = hit.bbox
                    break
            if not duplicate:
                merged.append(
                    OcrHit(
                        text=hit.text,
                        bbox=hit.bbox,
                        confidence=hit.confidence,
                        region=hit.region,
                        source=hit.source,
                    )
                )
        merged.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
        return merged

    def _scan_paragraph_strips(
        self,
        crop: np.ndarray,
        off: Tuple[int, int],
        roi_conf: float,
        *,
        use_easyocr: bool = True,
        use_paddle: bool = True,
    ) -> List[OcrHit]:
        """将高选区分条扫描，避免多行弹窗漏检中间行。"""
        from ocr_preprocess import _sharpen, _upscale, _white_text_mask

        ch, _cw = crop.shape[:2]
        if ch < 65:
            return []

        n_strips = max(2, min(6, (ch + 34) // 35))
        strip_h = max(24, ch // n_strips)
        overlap = max(10, strip_h // 5)
        hits: List[OcrHit] = []
        floor = max(0.04, roi_conf * 0.75)

        for i in range(n_strips):
            y0 = max(0, i * strip_h - overlap)
            y1 = min(ch, y0 + strip_h + overlap * 2)
            if y1 - y0 < 18:
                continue
            strip = crop[y0:y1, :]
            strip_off = (off[0], off[1] + y0)
            if use_easyocr and self._easyocr:
                variants = [
                    (_upscale(_white_text_mask(strip), 3.0), 3.0, f"strip{i}_w", EASYOCR_ROI_KW),
                    (_upscale(_sharpen(strip), 2.8), 2.8, f"strip{i}_s", EASYOCR_ROI_KW),
                    (_upscale(_white_text_mask(strip), 3.2), 3.2, f"strip{i}_p", EASYOCR_PARAGRAPH_KW),
                ]
                for img, scale, tag, kw in variants:
                    hits.extend(
                        self._hits_from_easyocr_image(
                            img, scale, strip_off, "dialog", tag,
                            read_kw=kw, min_conf=floor, max_width=1024,
                        )
                    )
            if use_paddle and self._paddle:
                hits.extend(
                    self._hits_from_paddle_image(
                        strip, 1.0, strip_off, "dialog", f"strip{i}_pad",
                        min_conf=max(0.18, floor),
                    )
                )
        return hits

    def _paddle_scan_roi(
        self,
        crop: np.ndarray,
        off: Tuple[int, int],
        *,
        is_paragraph: bool,
        paddle_conf: float,
    ) -> List[OcrHit]:
        """Paddle 主路径：原图 + 白字增强，段落模式加分条扫描。"""
        from ocr_preprocess import _upscale, _white_text_mask

        if not self._paddle:
            return []
        hits: List[OcrHit] = []
        variants: List[Tuple[np.ndarray, float, str]] = [(crop, 1.0, "raw")]
        white = _white_text_mask(crop)
        variants.append((_upscale(white, 2.0), 2.0, "white"))
        if is_paragraph:
            variants.append((_upscale(white, 2.4), 2.4, "white2"))
        for img, scale, tag in variants:
            hits.extend(
                self._hits_from_paddle_image(
                    img, scale, off, "dialog", tag, min_conf=paddle_conf,
                )
            )
        if is_paragraph:
            hits.extend(
                self._scan_paragraph_strips(
                    crop, off, paddle_conf, use_easyocr=False, use_paddle=True,
                )
            )
        return hits

    @staticmethod
    def _roi_result_sufficient(
        source: str,
        best_conf: float,
        is_para: bool,
        merged: List[OcrHit],
    ) -> bool:
        if not source or not merged:
            return False
        text_len = len(_compact_text(source))
        if is_para:
            return text_len >= 3
        if best_conf >= 0.28:
            return True
        return text_len >= 2 and best_conf >= 0.16

    def _scan_zone_variants(
        self,
        crop: np.ndarray,
        off: Tuple[int, int],
        region: str,
        name: str,
        scale: float,
        *,
        white: bool = False,
        adaptive: bool = False,
        saturated: bool = False,
    ) -> List[OcrHit]:
        from ocr_preprocess import _adaptive_text, _sharpen, _saturated_text, _upscale, _white_text_mask

        hits: List[OcrHit] = []
        base = _upscale(_sharpen(crop), scale)
        hits.extend(self._hits_from_easyocr_image(base, scale, off, region, name))
        if white:
            wimg = _upscale(_white_text_mask(crop), scale * 1.1)
            hits.extend(
                self._hits_from_easyocr_image(wimg, scale * 1.1, off, region, f"{name}_white")
            )
        if adaptive:
            aimg = _upscale(_adaptive_text(_sharpen(crop)), scale * 1.05)
            hits.extend(
                self._hits_from_easyocr_image(aimg, scale * 1.05, off, region, f"{name}_adapt")
            )
        if saturated:
            simg = _upscale(_saturated_text(crop), scale * 1.1)
            hits.extend(
                self._hits_from_easyocr_image(simg, scale * 1.1, off, region, f"{name}_color")
            )
        return hits

    def _scan_ui_zones(self, bgr: np.ndarray, gpu: bool) -> List[OcrHit]:
        """分区域 + 多路预处理扫描，提高 UI 覆盖率。"""
        from ocr_preprocess import crop_region, _sharpen, _upscale, _saturated_text, _white_text_mask

        # name, y0, y1, x0, x1, scale, region, white, adaptive, saturated
        zones = [
            ("bottom_menu", 0.72, 1.0, 0.0, 1.0, 2.8, "ui", True, False, False),
            ("center", 0.22, 0.80, 0.02, 0.98, 2.2, "dialog", True, True, False),
            ("right_ui", 0.02, 0.76, 0.52, 1.0, 2.5, "ui", True, False, True),
            ("left_ui", 0.02, 0.76, 0.0, 0.48, 2.5, "ui", True, False, True),
            ("top_bar", 0.0, 0.26, 0.0, 1.0, 2.6, "ui", True, True, False),
            ("top_mission", 0.02, 0.20, 0.28, 1.0, 2.8, "dialog", True, True, True),
        ]
        if not gpu:
            zones = [zones[0], zones[1], zones[4], zones[5]]

        all_hits: List[OcrHit] = []
        for name, y0, y1, x0, x1, scale, region, white, adaptive, saturated in zones:
            crop, off = crop_region(bgr, y0, y1, x0, x1)
            all_hits.extend(
                self._scan_zone_variants(
                    crop, off, region, name, scale,
                    white=white, adaptive=adaptive, saturated=saturated,
                )
            )

        # 底部彩色大字 / 字幕
        color, off2 = crop_region(bgr, 0.45, 0.98, 0.03, 0.97)
        color = _upscale(_saturated_text(color), 2.5)
        all_hits.extend(self._hits_from_easyocr_image(color, 2.5, off2, "subtitle", "color_sub"))
        white_sub, off3 = crop_region(bgr, 0.50, 0.98, 0.02, 0.98)
        white_sub = _upscale(_white_text_mask(white_sub), 2.8)
        all_hits.extend(self._hits_from_easyocr_image(white_sub, 2.8, off3, "subtitle", "white_sub"))

        if gpu and self._coverage_boost:
            base = _sharpen(bgr)
            small, inv_scale = _resize_for_ocr(base, OCR_FULL_PREVIEW_WIDTH)
            all_hits.extend(
                self._hits_from_easyocr_image(small, inv_scale, (0, 0), "full", "full_preview")
            )
            white_full, inv2 = _resize_for_ocr(_white_text_mask(base), OCR_FULL_PREVIEW_WIDTH)
            all_hits.extend(
                self._hits_from_easyocr_image(white_full, inv2, (0, 0), "full", "full_white")
            )
        return all_hits

    def recognize_roi(
        self,
        bgr: np.ndarray,
        roi: Tuple[int, int, int, int],
        *,
        compact: bool = True,
    ) -> Tuple[List[OcrHit], str, bool]:
        """对用户框选区域 OCR：先快后慢两阶段；返回 (hits, 原文, 是否多行段落)。"""
        from ocr_preprocess import (
            _adaptive_text,
            _artistic_stroke_text,
            _green_button_text,
            _sharpen,
            _upscale,
            _white_text_mask,
        )

        fh, fw = bgr.shape[:2]
        # roi 为 (0,0,w,h) 当传入已是裁剪图时
        if roi == (0, 0, fw, fh):
            x1, y1, x2, y2 = 0, 0, fw, fh
            crop = bgr
            off = (0, 0)
        else:
            x1, y1, x2, y2 = roi
            x1, y1 = max(0, min(fw, x1)), max(0, min(fh, y1))
            x2, y2 = max(0, min(fw, x2)), max(0, min(fh, y2))
            if x2 - x1 < 10 or y2 - y1 < 10:
                return [], "", False
            crop = bgr[y1:y2, x1:x2].copy()
            off = (x1, y1)

        roi_box = (x1, y1, x2, y2)
        roi_kw = EASYOCR_ROI_KW
        roi_conf = self._min_confidence("dialog", "easyocr", roi=True)
        ch, cw = crop.shape[:2]
        is_paragraph = roi_is_paragraph(ch, cw)
        is_wide_btn = (not is_paragraph) and cw >= 110 and ch < 140
        is_menu_btn = ch < 180 and cw < 520
        is_tall_icon = (not is_paragraph) and (not is_wide_btn) and ch > cw * 0.95
        is_side_icon = cw < 220 and ch < 220

        def run_variants(
            variant_list: list,
            base_crop: np.ndarray,
            base_off: Tuple[int, int],
            *,
            read_kw: Optional[dict] = None,
        ) -> List[OcrHit]:
            hits: List[OcrHit] = []
            kw_default = read_kw or roi_kw
            for img, scale, tag, kw in variant_list:
                hits.extend(
                    self._hits_from_easyocr_image(
                        img, scale, base_off, "dialog", f"roi_{tag}",
                        read_kw=kw or kw_default, min_conf=roi_conf, max_width=1024,
                    )
                )
            return hits

        def merge_roi_hits(raw_hits: List[OcrHit]) -> List[OcrHit]:
            use_para = is_paragraph or infer_paragraph_from_hits(raw_hits, ch, cw)
            if use_para:
                return self._merge_hits_paragraph(raw_hits)
            return self._merge_hits(raw_hits, (fw, fh))

        text_crop = crop
        text_off = off
        if is_tall_icon:
            split = int(ch * 0.35)
            text_crop = crop[split:, :].copy()
            text_off = (off[0], off[1] + split)
        elif is_wide_btn:
            split = int(ch * 0.42)
            text_crop = crop[split:, :].copy()
            text_off = (off[0], off[1] + split)

        paddle_conf = max(0.18, self._min_confidence("dialog", "paddle", roi=True) * 0.85)
        scan_crop = crop if is_paragraph else text_crop
        scan_off = off if is_paragraph else text_off
        all_hits: List[OcrHit] = []

        def finalize(raw_hits: List[OcrHit]) -> Tuple[List[OcrHit], str, bool]:
            merged_local = merge_roi_hits(raw_hits)
            src, para = pick_roi_source(merged_local, roi_box, ch, cw)
            if not para and infer_paragraph_from_hits(merged_local, ch, cw):
                para = True
                src = assemble_roi_text(merged_local)
            return merged_local, src, para

        # --- 主引擎：Paddle（GPU 优先）---
        if self._paddle:
            all_hits = self._paddle_scan_roi(
                scan_crop, scan_off, is_paragraph=is_paragraph, paddle_conf=paddle_conf,
            )
            merged, source, is_para = finalize(all_hits)
            best_conf = max((h.confidence for h in merged), default=0.0)
            if self._roi_result_sufficient(source, best_conf, is_para, merged):
                _release_gpu_cache()
                return merged, source, is_para

        # --- 备用：EasyOCR（仅 Paddle 不足时，减少预处理路数 ---
        if not self._easyocr:
            merged, source, is_para = finalize(all_hits)
            _release_gpu_cache()
            return merged, source, is_para

        if is_paragraph:
            fast = [
                (_upscale(_white_text_mask(crop), 3.0), 3.0, "white", roi_kw),
                (_upscale(_white_text_mask(crop), 3.2), 3.2, "para", EASYOCR_PARAGRAPH_KW),
            ]
            all_hits.extend(run_variants(fast, crop, off))
            all_hits.extend(
                self._scan_paragraph_strips(
                    crop, off, roi_conf, use_easyocr=True, use_paddle=False,
                )
            )
        elif is_wide_btn:
            fast = [
                (_upscale(_white_text_mask(text_crop), 3.0), 3.0, "white", roi_kw),
                (_upscale(_green_button_text(text_crop), 2.8), 2.8, "green", roi_kw),
            ]
            all_hits.extend(run_variants(fast, text_crop, text_off))
        else:
            fast = [
                (_upscale(_white_text_mask(text_crop), 2.4), 2.4, "white", roi_kw),
                (_upscale(_green_button_text(text_crop), 2.4), 2.4, "green", roi_kw),
            ]
            if is_side_icon:
                fast.append((_upscale(_sharpen(text_crop), 2.4), 2.4, "sharp", roi_kw))
            all_hits.extend(run_variants(fast, text_crop, text_off))

        merged, source, is_para = finalize(all_hits)
        best_conf = max((h.confidence for h in merged), default=0.0)

        need_slow = is_para or not source or best_conf < 0.38
        if need_slow:
            slow_crop = crop if is_para else text_crop
            slow_off = off if is_para else text_off
            slow = [
                (_upscale(_white_text_mask(slow_crop), 3.2), 3.2, "white2", roi_kw),
                (_upscale(_adaptive_text(_sharpen(slow_crop)), 3.0), 3.0, "adapt", roi_kw),
            ]
            if is_para:
                slow.append((_upscale(_white_text_mask(slow_crop), 3.4), 3.4, "para2", EASYOCR_PARAGRAPH_KW))
            all_hits.extend(run_variants(slow, slow_crop, slow_off))
            if is_para:
                all_hits.extend(
                    self._scan_paragraph_strips(
                        slow_crop, slow_off, roi_conf * 0.9,
                        use_easyocr=True, use_paddle=bool(self._paddle),
                    )
                )
            merged, source, is_para = finalize(all_hits)

        _release_gpu_cache()
        return merged, source, is_para

    def recognize(self, bgr: np.ndarray, subtitle_boost: bool = True) -> List[OcrHit]:
        fh, fw = bgr.shape[:2]
        frame_size = (fw, fh)

        if self._easyocr is not None and self._fast_mode:
            all_hits = self._scan_ui_zones(bgr, gpu=self._use_gpu)
            return self._merge_hits(all_hits, frame_size)

        variants = build_preprocess_variants(bgr, subtitle_boost=subtitle_boost)
        all_hits: List[OcrHit] = []

        if self._easyocr is not None:
            priority = ("subtitle_color_x3", "prompt_x2.5")
            picked = [v for v in variants if v.name in priority] or variants[:2]
            for v in picked:
                all_hits.extend(self._ocr_variant(v))
        elif self._paddle is not None:
            priority = {
                "subtitle_adapt_x2.8", "subtitle_x2.2", "subtitle_white_x2.5", "subtitle_color_x3",
                "prompt_x2.5", "full_x1.5", "dialog_x1.8", "full_std", "full_x2",
            }
            variants = [v for v in variants if v.name in priority] or variants[:10]
            for v in variants:
                all_hits.extend(self._ocr_variant(v))
        else:
            for v in variants:
                all_hits.extend(self._ocr_variant(v))
        return self._merge_hits(all_hits, frame_size)
