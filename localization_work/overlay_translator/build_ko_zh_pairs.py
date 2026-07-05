"""
从 Frida 抓取的韩文 + 国服文本池，生成 ko_zh_pairs.json。

配对策略（按优先级）:
  1. 已有 KO_GAME_GLOSSARY
  2. Frida 抓取 → 机翻 → 国服 game_strings 模糊匹配 → 官方繁中转简体
  3. 仅机翻（标记 source=mt）

用法:
  py -3 build_ko_zh_pairs.py
  py -3 build_ko_zh_pairs.py --no-mt   # 跳过 Bing，仅保留已有表项
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
DEFAULT_CAPTURE = WORK / "frida" / "ko_captured.jsonl"
DEFAULT_OUT = ROOT / "ko_zh_pairs.json"
GAME_STRINGS = ROOT / "game_strings_zh.json"

sys.path.insert(0, str(ROOT))

from game_string_db import GameStringDB, get_game_string_db
from translator_backends import KO_GAME_GLOSSARY, _compact_ko, translate_game_text

HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")


def _load_captured(path: Path) -> list[str]:
    if not path.is_file():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            t = (row.get("text") or "").strip()
        except json.JSONDecodeError:
            t = line
        if not t or not HANGUL_RE.search(t):
            continue
        key = _compact_ko(t)
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _pair_one(ko: str, *, use_mt: bool, gdb: GameStringDB) -> dict | None:
    compact = _compact_ko(ko)
    if compact in {_compact_ko(k) for k in KO_GAME_GLOSSARY}:
        for k, v in KO_GAME_GLOSSARY.items():
            if _compact_ko(k) == compact:
                return {"ko": ko, "zh": v, "source": "glossary", "confidence": 1.0}

    if not use_mt:
        return None

    mt = translate_game_text(ko, dialog=len(ko) > 30)
    if not mt or HANGUL_RE.search(mt):
        return None

    official = gdb.refine_translation(mt, paragraph=len(ko) > 30)
    if official:
        return {
            "ko": ko,
            "zh": official,
            "source": "frida+official",
            "confidence": 0.88,
            "mt": mt,
        }

    return {
        "ko": ko,
        "zh": mt,
        "source": "frida+mt",
        "confidence": 0.65,
    }


def build_pairs(
    capture_path: Path = DEFAULT_CAPTURE,
    out_path: Path = DEFAULT_OUT,
    *,
    use_mt: bool = True,
) -> dict:
    gdb = get_game_string_db()
    if not gdb.available and GAME_STRINGS.is_file():
        gdb.load(GAME_STRINGS)

    captured = _load_captured(capture_path)
    pairs: dict[str, dict] = {}

    for k, v in KO_GAME_GLOSSARY.items():
        ck = _compact_ko(k)
        if ck not in pairs:
            pairs[ck] = {"ko": k, "zh": v, "source": "glossary", "confidence": 1.0}

    for ko in captured:
        ck = _compact_ko(ko)
        if ck in pairs:
            continue
        item = _pair_one(ko, use_mt=use_mt, gdb=gdb)
        if item:
            pairs[ck] = item

    payload = {
        "version": 1,
        "count": len(pairs),
        "pairs": list(pairs.values()),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    by_source = {}
    for p in pairs.values():
        by_source[p["source"]] = by_source.get(p["source"], 0) + 1
    return {"count": len(pairs), "by_source": by_source, "path": str(out_path.name)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mt", action="store_true", help="不调用 Bing，仅 glossary")
    ap.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    result = build_pairs(args.capture, args.out, use_mt=not args.no_mt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
