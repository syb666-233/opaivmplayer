"""
从国服 APK 扫描结果精炼文本，生成 game_strings_zh.json 供翻译器模糊匹配。

用法（国服 cn_strings_raw.txt 在 localization_work/ 下）:
  py -3 build_game_strings.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
RAW_PATH = WORK / "cn_strings_raw.txt"
OUT_PATH = ROOT / "game_strings_zh.json"

DIALOGUE_END = re.compile(r"[。！？…」』]$")
HAS_QUOTE = re.compile(r"[「『]")
# 拉长的装饰符号（游戏台词里常见，不应拉低汉字占比）
_DECOR_RE = re.compile(r"[—\-…\.·\s]+")


def _han_count(s: str) -> int:
    return sum(1 for c in s if "\u4e00" <= c <= "\u9fff")


def _content_length(s: str) -> int:
    """去掉 ——、…… 等装饰后用于计算汉字占比的有效长度。"""
    return len(_DECOR_RE.sub("", s))


def _han_ratio(s: str) -> float:
    han = _han_count(s)
    denom = max(han, _content_length(s), 1)
    return han / denom


def _is_char_table(s: str) -> bool:
    """识别 Unicode 字表/字典串（如连续生僻汉字），不误伤带标点的正常繁体台词。"""
    if len(s) < 40:
        return False
    han = _han_count(s)
    if han < 20:
        return False
    # 正常句子几乎都有标点；无标点且汉字种类极多 → 字表
    if not re.search(r"[。！？，、；：「」『』]", s):
        unique_han = len(set(c for c in s if "\u4e00" <= c <= "\u9fff"))
        if unique_han / han > 0.82:
            return True
    return False


def _filter_line(s: str) -> bool:
    s = s.strip()
    if len(s) < 2 or len(s) > 500:
        return False
    if _han_ratio(s) < 0.45:
        return False
    if re.search(r"[A-Za-z]{8,}", s):
        return False
    if re.search(r"[\u0080-\u024f]{2,}", s):
        return False
    if _is_char_table(s):
        return False
    return True


def _dedupe(strings: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for s in sorted(strings, key=len, reverse=True):
        key = re.sub(r"\s+", "", s)
        if key not in seen:
            seen[key] = s
    return list(seen.values())


def main() -> None:
    if not RAW_PATH.is_file():
        print(f"未找到 {RAW_PATH}，请先运行 analyze_cn_apk.py 扫描国服 APK")
        sys.exit(1)

    raw_lines = RAW_PATH.read_text(encoding="utf-8").splitlines()
    filtered = [ln.strip() for ln in raw_lines if _filter_line(ln.strip())]
    strings = _dedupe(filtered)
    strings.sort(key=len)

    payload = {
        "version": 1,
        "source": str(RAW_PATH.name),
        "count": len(strings),
        "strings": strings,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ui = sum(1 for s in strings if len(s) <= 12)
    dialogue = sum(1 for s in strings if len(s) > 12)
    print(f"已写入 {OUT_PATH.name}: {len(strings)} 条 (UI短词 {ui}, 对话/说明 {dialogue})")


if __name__ == "__main__":
    main()
