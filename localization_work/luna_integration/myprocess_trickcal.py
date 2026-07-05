# Trickcal 译前/译后优化（Luna userconfig/myprocess.py）
# - 译前：韩中对照表直出（预置词典 + 运行时学习词条）
# - 译后：国服文本池模糊纠错 + 静默学习（方案 C）
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    from opencc import OpenCC

    _OPENCC = OpenCC("t2s")
except ImportError:
    _OPENCC = None

HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")
_PUNCT = re.compile(
    r"[\s\d\.,!?·…「」『』（）:;，。！？、—\-\u201c\u201d\u2018\u2019《》【】\[\]()]+"
)

_DIRECT_CONF = 0.82
_THRESH_SHORT = 0.84
_THRESH_MID = 0.72
_THRESH_LONG = 0.68
_MAX_LEARNED = 8000


def _simp(text: str) -> str:
    if _OPENCC is not None:
        return _OPENCC.convert(text or "")
    return text or ""


def _norm(text: str) -> str:
    return _PUNCT.sub("", _simp(text))


def _compact_ko(text: str) -> str:
    return "".join((text or "").split())


def _resolve_dirs() -> tuple[Path, Path]:
    """返回 (data_dir, userconfig_dir)。"""
    here = Path(__file__).resolve()
    if here.parent.name == "userconfig":
        uc = here.parent
        data = uc.parent / "data"
    else:
        uc = here.parent
        data = here.parent / "data"
        if not data.is_dir():
            data = here.parent.parent / "LunaTrickcal" / "runtime" / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data, uc


def _find_data_paths() -> tuple[Path | None, Path | None]:
    here = Path(__file__).resolve()
    roots = [
        here.parent.parent / "data" if here.parent.name == "userconfig" else None,
        here.parent.parent / "LunaTrickcal" / "data",
        here.parent.parent / "overlay_translator",
        here.parent / "data",
        here.parent.parent / "data",
    ]
    game_strings = ko_pairs = None
    for root in roots:
        if root is None or not root.is_dir():
            continue
        gs = root / "game_strings_zh.json"
        kp = root / "ko_zh_pairs.json"
        if game_strings is None and gs.is_file():
            game_strings = gs
        if ko_pairs is None and kp.is_file():
            ko_pairs = kp
    return game_strings, ko_pairs


class _KoZhIndex:
    """韩→中直查表（预置词典 + 运行时学习）。"""

    def __init__(self) -> None:
        self._by_compact: dict[str, dict] = {}
        self._load()

    def _ingest_item(self, item: dict) -> None:
        if not isinstance(item, dict):
            return
        ko = (item.get("ko") or item.get("src") or "").strip()
        zh = (item.get("zh") or item.get("dst") or "").strip()
        if not ko or not zh:
            return
        ck = _compact_ko(ko)
        conf = float(item.get("confidence", 0.9))
        prev = self._by_compact.get(ck)
        if prev is None or conf > prev.get("confidence", 0):
            self._by_compact[ck] = {
                "ko": ko,
                "zh": _simp(zh),
                "confidence": conf,
                "source": item.get("source", "dict"),
            }

    def _load(self) -> None:
        _, pairs_path = _find_data_paths()
        data_dir, uc = _resolve_dirs()
        candidates = []
        if pairs_path:
            candidates.append(pairs_path)
        candidates.extend(
            [
                data_dir / "learned_pairs.json",
                data_dir / "trickcal_noundict.json",
                uc / "trickcal_noundict.json",
            ]
        )
        for path in candidates:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items = data.get("pairs") or data.get("entries") or []
            for item in items:
                self._ingest_item(item)

    def add_entry(self, ko: str, zh: str, confidence: float, source: str) -> None:
        ck = _compact_ko(ko)
        prev = self._by_compact.get(ck)
        if prev and prev.get("confidence", 0) >= confidence:
            return
        self._by_compact[ck] = {
            "ko": ko,
            "zh": _simp(zh),
            "confidence": confidence,
            "source": source,
        }

    def lookup(self, ko: str) -> dict | None:
        if not ko or not HANGUL_RE.search(ko):
            return None
        ck = _compact_ko(ko)
        hit = self._by_compact.get(ck)
        if hit and hit.get("confidence", 0) >= _DIRECT_CONF:
            return hit
        if len(ck) <= 20:
            best = None
            best_len = 0
            for k, v in self._by_compact.items():
                if len(k) < 2:
                    continue
                if k in ck or ck in k:
                    if v.get("confidence", 0) >= _DIRECT_CONF and len(k) > best_len:
                        best = v
                        best_len = len(k)
            return best
        return None


class _SessionLearner:
    """方案 C：OCR 翻译过程中静默积累韩中对照。"""

    def __init__(self, index: _KoZhIndex) -> None:
        self._index = index
        self._lock = threading.Lock()
        self._data_dir, self._uc_dir = _resolve_dirs()
        self._jsonl = self._data_dir / "learned_pairs.jsonl"
        self._merged = self._data_dir / "learned_pairs.json"
        self._cfg_path = self._uc_dir / "trickcal_learn_config.json"
        self._cfg = self._load_cfg()
        self._pending: dict[str, dict] = {}
        self._known: set[str] = set()
        self._load_known()

    def _load_cfg(self) -> dict:
        defaults = {
            "enabled": True,
            "min_repeats": 3,
            "min_ko_len": 2,
            "max_ko_len": 120,
        }
        if not self._cfg_path.is_file():
            return defaults
        try:
            data = json.loads(self._cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
        return defaults

    def _load_known(self) -> None:
        for ck in self._index._by_compact:
            self._known.add(ck)
        if not self._merged.is_file():
            return
        try:
            data = json.loads(self._merged.read_text(encoding="utf-8"))
            for item in data.get("pairs") or []:
                ko = (item.get("ko") or "").strip()
                if ko:
                    self._known.add(_compact_ko(ko))
        except Exception:
            pass

    def _valid_ko(self, ko: str) -> bool:
        if not ko or not HANGUL_RE.search(ko):
            return False
        ck = _compact_ko(ko)
        lo = int(self._cfg.get("min_ko_len", 2))
        hi = int(self._cfg.get("max_ko_len", 120))
        return lo <= len(ck) <= hi

    def _valid_zh(self, zh: str) -> bool:
        if not zh or not zh.strip():
            return False
        if HANGUL_RE.search(zh):
            return False
        if len(_norm(zh)) < 1:
            return False
        return True

    def observe(
        self,
        ko: str,
        zh: str,
        *,
        source: str = "session",
        pool_hit: bool = False,
    ) -> None:
        if not self._cfg.get("enabled", True):
            return
        ko = (ko or "").strip()
        zh = _simp((zh or "").strip())
        if not self._valid_ko(ko) or not self._valid_zh(zh):
            return
        ck = _compact_ko(ko)
        if ck in self._known:
            return

        if pool_hit:
            self._commit(ko, zh, source="official_pool", confidence=0.88)
            return

        with self._lock:
            p = self._pending.get(ck)
            if p is None or p["zh"] != zh:
                self._pending[ck] = {"ko": ko, "zh": zh, "count": 1}
                return
            p["count"] += 1
            need = int(self._cfg.get("min_repeats", 3))
            if p["count"] >= need:
                conf = min(0.82, 0.74 + (p["count"] - need) * 0.02)
                self._commit(ko, zh, source=source, confidence=conf)
                del self._pending[ck]

    def _commit(self, ko: str, zh: str, source: str, confidence: float) -> None:
        ck = _compact_ko(ko)
        if ck in self._known:
            return
        self._known.add(ck)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ko": ko,
            "zh": zh,
            "source": source,
            "confidence": confidence,
        }
        with self._lock:
            self._jsonl.parent.mkdir(parents=True, exist_ok=True)
            with self._jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            pairs = []
            if self._merged.is_file():
                try:
                    pairs = json.loads(self._merged.read_text(encoding="utf-8")).get(
                        "pairs", []
                    )
                except Exception:
                    pairs = []
            pairs.append(
                {"ko": ko, "zh": zh, "source": source, "confidence": confidence}
            )
            if len(pairs) > _MAX_LEARNED:
                pairs = pairs[-_MAX_LEARNED:]
            self._merged.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "count": len(pairs),
                        "pairs": pairs,
                        "updated_at": row["ts"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        self._index.add_entry(ko, zh, confidence, source)


class _StringPool:
    """国服 APK 中文文本池 — 译后模糊纠错。"""

    def __init__(self) -> None:
        self._strings: list[str] = []
        self._norm: list[str] = []
        self._by_len: dict[int, list[int]] = {}
        self._load()

    def _load(self) -> None:
        gs_path, _ = _find_data_paths()
        if not gs_path or not gs_path.is_file():
            return
        try:
            data = json.loads(gs_path.read_text(encoding="utf-8"))
            self._strings = [s for s in data.get("strings") or [] if isinstance(s, str)]
            self._norm = [_norm(s) for s in self._strings]
            for i, n in enumerate(self._norm):
                if n:
                    self._by_len.setdefault(len(n), []).append(i)
        except Exception:
            pass

    def refine(self, mt: str) -> str | None:
        nq = _norm(mt)
        if len(nq) < 4:
            return None
        lo, hi = max(1, int(len(nq) * 0.55)), int(len(nq) * 1.65) + 2
        best_i, best = -1, 0.0
        for length in range(lo, hi + 1):
            for i in self._by_len.get(length, []):
                nc = self._norm[i]
                if not nc:
                    continue
                sc = SequenceMatcher(None, nq, nc).ratio()
                if sc > best:
                    best, best_i = sc, i
        if len(nq) <= 16:
            th = _THRESH_SHORT
        elif len(nq) <= 40:
            th = _THRESH_MID
        else:
            th = _THRESH_LONG
        if best_i >= 0 and best >= th:
            return _simp(self._strings[best_i])
        return None


_KO_ZH = _KoZhIndex()
_POOL = _StringPool()
_LEARNER = _SessionLearner(_KO_ZH)


class Process:
    def process_before(self, text: str):
        if not text or not text.strip():
            return text, None
        ko = text.strip()
        hit = _KO_ZH.lookup(ko)
        if hit:
            return text, {
                "direct_zh": hit["zh"],
                "ko": ko,
                "ko_zh_source": hit.get("source"),
                "ko_zh_conf": hit.get("confidence"),
            }
        return text, {"ko": ko}

    def process_after(self, res: str, context):
        if context and context.get("direct_zh"):
            return context["direct_zh"]
        if not res or not res.strip():
            return res
        ko = (context or {}).get("ko") or ""
        refined = _POOL.refine(res)
        final = refined if refined else res
        if ko and HANGUL_RE.search(ko):
            if refined:
                _LEARNER.observe(ko, refined, pool_hit=True)
            else:
                _LEARNER.observe(ko, final, source="session")
        return final
