"""国服 APK 文本池：机器翻译结果 → 模糊匹配官方中文。"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

try:
    from opencc import OpenCC

    _OPENCC = OpenCC("t2s")
except ImportError:
    _OPENCC = None

_DB_PATH = Path(__file__).with_name("game_strings_zh.json")
_PUNCT_RE = re.compile(
    r"[\s\d\.,!?·…「」『』（）:;，。！？、—\-\"'""''《》【】\[\]()]+"
)


def _to_simplified(text: str) -> str:
    if not text:
        return ""
    if _OPENCC is not None:
        return _OPENCC.convert(text)
    return text


def _normalize(text: str) -> str:
    t = _to_simplified(text or "")
    t = _PUNCT_RE.sub("", t)
    return t


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


class GameStringDB:
    def __init__(self) -> None:
        self._strings: List[str] = []
        self._norm: List[str] = []
        self._by_len: Dict[int, List[int]] = {}
        self._loaded = False
        self._enabled = True

    @property
    def available(self) -> bool:
        return self._loaded and bool(self._strings)

    @property
    def count(self) -> int:
        return len(self._strings)

    def load(self, path: Optional[Path] = None) -> bool:
        p = path or _DB_PATH
        if not p.is_file():
            self._loaded = False
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            strings = data.get("strings") or []
            self._strings = [s for s in strings if isinstance(s, str) and s.strip()]
            self._norm = [_normalize(s) for s in self._strings]
            self._by_len = {}
            for i, n in enumerate(self._norm):
                if not n:
                    continue
                self._by_len.setdefault(len(n), []).append(i)
            self._loaded = True
            return True
        except Exception:
            self._loaded = False
            self._strings = []
            self._norm = []
            self._by_len = {}
            return False

    def _candidate_indices(self, norm_q: str) -> List[int]:
        ql = len(norm_q)
        if ql < 1:
            return []
        lo = max(1, int(ql * 0.55))
        hi = max(lo, int(ql * 1.65) + 2)
        out: List[int] = []
        for length in range(lo, hi + 1):
            out.extend(self._by_len.get(length, []))
        return out

    def _score(self, norm_q: str, norm_c: str) -> float:
        if not norm_q or not norm_c:
            return 0.0
        if norm_q == norm_c:
            return 1.0
        if norm_q in norm_c or norm_c in norm_q:
            shorter = min(len(norm_q), len(norm_c))
            longer = max(len(norm_q), len(norm_c))
            if shorter / longer >= 0.72:
                return 0.92
        bq, bc = _bigrams(norm_q), _bigrams(norm_c)
        if bq and bc:
            overlap = len(bq & bc) / len(bq)
            if overlap < 0.28:
                return 0.0
        return SequenceMatcher(None, norm_q, norm_c).ratio()

    def _threshold(self, norm_q: str, *, paragraph: bool) -> float:
        ql = len(norm_q)
        if ql <= 8:
            return 0.90
        if ql <= 16:
            return 0.84
        if paragraph or ql > 40:
            return 0.68
        return 0.74

    def refine_translation(self, mt_text: str, *, paragraph: bool = False) -> Optional[str]:
        """若机器翻译与国服文本池足够接近，返回官方译法（简体）。"""
        if not self._enabled or not self.available:
            return None
        raw = (mt_text or "").strip()
        if not raw or len(raw) < 2:
            return None
        norm_q = _normalize(raw)
        if len(norm_q) < 2:
            return None

        threshold = self._threshold(norm_q, paragraph=paragraph)
        best_idx = -1
        best_score = 0.0

        for idx in self._candidate_indices(norm_q):
            score = self._score(norm_q, self._norm[idx])
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx < 0 or best_score < threshold:
            return None
        official = self._strings[best_idx]
        return _to_simplified(official)


_instance: Optional[GameStringDB] = None


def get_game_string_db() -> GameStringDB:
    global _instance
    if _instance is None:
        _instance = GameStringDB()
        _instance.load()
    return _instance
