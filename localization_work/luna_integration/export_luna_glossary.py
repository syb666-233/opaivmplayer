"""
导出 Trickcal 韩中对照表 → LunaTranslator「专有名词翻译」格式。

输入:
  overlay_translator/ko_zh_pairs.json
  overlay_translator/game_strings_zh.json (可选，仅用于统计)

输出:
  luna_integration/trickcal_noundict.json
  luna_integration/trickcal_noundict.tsv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
KO_ZH = ROOT / "overlay_translator" / "ko_zh_pairs.json"
OUT_JSON = Path(__file__).resolve().parent / "trickcal_noundict.json"
OUT_TSV = Path(__file__).resolve().parent / "trickcal_noundict.tsv"


def _compact(s: str) -> str:
    return "".join(s.split())


def load_pairs() -> list[dict]:
    if not KO_ZH.is_file():
        raise FileNotFoundError(f"未找到 {KO_ZH}，请先运行 build_ko_zh_pairs.bat")
    data = json.loads(KO_ZH.read_text(encoding="utf-8"))
    pairs = data.get("pairs") or []
    out: list[dict] = []
    seen: set[str] = set()
    for item in pairs:
        if not isinstance(item, dict):
            continue
        ko = (item.get("ko") or "").strip()
        zh = (item.get("zh") or "").strip()
        if not ko or not zh:
            continue
        key = _compact(ko)
        if key in seen:
            continue
        seen.add(key)
        src = ko
        info = item.get("source") or "trickcal"
        conf = item.get("confidence")
        if conf is not None:
            info = f"{info}|conf={conf}"
        out.append({"src": src, "dst": zh, "info": info})
    out.sort(key=lambda x: len(_compact(x["src"])), reverse=True)
    return out


def main() -> None:
    entries = load_pairs()
    payload = {
        "version": 1,
        "game": "Trickcal Revive (com.epidgames.trickcalrevive)",
        "count": len(entries),
        "luna_format": "noundictconfig_ex items: src, dst, info",
        "entries": entries,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["src\tdst\tinfo"]
    for e in entries:
        lines.append(f"{e['src']}\t{e['dst']}\t{e['info']}")
    OUT_TSV.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {OUT_JSON.name}: {len(entries)} 条")
    print(f"已写入 {OUT_TSV.name}")


if __name__ == "__main__":
    main()
