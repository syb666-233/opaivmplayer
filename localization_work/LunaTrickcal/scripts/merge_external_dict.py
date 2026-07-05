"""
合并外部贡献的韩中词条到 ko_zh_pairs.json。

用法:
  py -3 merge_external_dict.py
  py -3 merge_external_dict.py --dir path/to/contributions

支持格式:
  - *.json: {"entries":[{"src"/"ko","dst"/"zh","info"?}]}
  - *.tsv:  src\\tdst\\tinfo (首行可为表头)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "contributions"
KO_ZH = ROOT.parent / "overlay_translator" / "ko_zh_pairs.json"


def _compact(s: str) -> str:
    return "".join((s or "").split())


def _load_json_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        items = data
    else:
        items = data.get("entries") or data.get("pairs") or []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ko = (item.get("ko") or item.get("src") or "").strip()
        zh = (item.get("zh") or item.get("dst") or "").strip()
        if ko and zh:
            out.append(
                {
                    "ko": ko,
                    "zh": zh,
                    "source": item.get("source") or f"contrib:{path.stem}",
                    "confidence": float(item.get("confidence", 0.95)),
                }
            )
    return out


def _load_tsv_file(path: Path) -> list[dict]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if i == 0 and parts[0].lower() in ("src", "ko", "原文"):
            continue
        if len(parts) < 2:
            continue
        ko, zh = parts[0].strip(), parts[1].strip()
        info = parts[2].strip() if len(parts) > 2 else f"contrib:{path.stem}"
        if ko and zh:
            out.append(
                {
                    "ko": ko,
                    "zh": zh,
                    "source": info,
                    "confidence": 0.95,
                }
            )
    return out


def collect_contributions(contrib_dir: Path) -> list[dict]:
    if not contrib_dir.is_dir():
        return []
    items: list[dict] = []
    for path in sorted(contrib_dir.iterdir()):
        if path.name.startswith("example_"):
            continue
        if path.suffix.lower() == ".json":
            items.extend(_load_json_file(path))
        elif path.suffix.lower() == ".tsv":
            items.extend(_load_tsv_file(path))
    return items


def merge_into_ko_zh(contrib: list[dict], ko_zh_path: Path) -> dict:
    if ko_zh_path.is_file():
        data = json.loads(ko_zh_path.read_text(encoding="utf-8"))
        pairs_list = data.get("pairs") or []
    else:
        data = {"version": 1, "pairs": []}
        pairs_list = []

    by_key = {_compact(p.get("ko", "")): p for p in pairs_list if isinstance(p, dict)}
    added = updated = 0
    for item in contrib:
        ck = _compact(item["ko"])
        if ck in by_key:
            prev = by_key[ck]
            if prev.get("zh") != item["zh"]:
                by_key[ck] = item
                updated += 1
        else:
            by_key[ck] = item
            added += 1

    merged = sorted(by_key.values(), key=lambda x: len(_compact(x.get("ko", ""))), reverse=True)
    data["pairs"] = merged
    data["count"] = len(merged)
    ko_zh_path.parent.mkdir(parents=True, exist_ok=True)
    ko_zh_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "updated": updated, "total": len(merged), "path": str(ko_zh_path)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--ko-zh", type=Path, default=KO_ZH)
    args = ap.parse_args()

    contrib = collect_contributions(args.dir)
    if not contrib:
        print(json.dumps({"contrib_dir": str(args.dir), "merged": 0, "note": "无贡献文件"}, ensure_ascii=False))
        return
    result = merge_into_ko_zh(contrib, args.ko_zh)
    result["contrib_count"] = len(contrib)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
