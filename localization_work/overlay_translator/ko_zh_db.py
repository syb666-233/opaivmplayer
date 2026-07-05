"""Frida / 配对表韩文 → 中文查表。"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).with_name("ko_zh_pairs.json")
_HANGUL = re.compile(r"[\uAC00-\uD7AF]")


def _compact_ko(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


class KoZhDB:
    def __init__(self) -> None:
        self._by_compact: dict[str, str] = {}
        self._keys_by_len: list[str] = []
        self._loaded = False

    @property
    def available(self) -> bool:
        return self._loaded and bool(self._by_compact)

    @property
    def count(self) -> int:
        return len(self._by_compact)

    def load(self, path: Optional[Path] = None) -> bool:
        p = path or _DB_PATH
        if not p.is_file():
            self._loaded = False
            self._by_compact = {}
            self._keys_by_len = []
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            pairs = data.get("pairs") or []
            table: dict[str, str] = {}
            for item in pairs:
                if not isinstance(item, dict):
                    continue
                ko = (item.get("ko") or "").strip()
                zh = (item.get("zh") or "").strip()
                if not ko or not zh:
                    continue
                table[_compact_ko(ko)] = zh
            self._by_compact = table
            self._keys_by_len = sorted(table.keys(), key=len, reverse=True)
            self._loaded = True
            return True
        except Exception:
            self._loaded = False
            self._by_compact = {}
            self._keys_by_len = []
            return False

    def lookup(self, text: str, *, min_ratio: float = 0.82) -> Optional[str]:
        if not self.available:
            return None
        raw = (text or "").strip()
        if not raw:
            return None
        compact = _compact_ko(raw)
        if compact in self._by_compact:
            return self._by_compact[compact]

        best_key: Optional[str] = None
        best_score = 0.0
        for key in self._keys_by_len:
            if len(key) < 2:
                continue
            if key in compact or compact in key:
                score = SequenceMatcher(None, compact, key).ratio()
                if score > best_score:
                    best_score = score
                    best_key = key
            elif len(compact) <= 16:
                score = SequenceMatcher(None, compact, key).ratio()
                if score > best_score:
                    best_score = score
                    best_key = key

        if best_key and best_score >= min_ratio:
            return self._by_compact[best_key]
        return None


_instance: Optional[KoZhDB] = None


def get_ko_zh_db() -> KoZhDB:
    global _instance
    if _instance is None:
        _instance = KoZhDB()
        _instance.load()
    return _instance
