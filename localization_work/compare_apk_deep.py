"""
韩版 vs 国服 APK 深度结构对比，产出 apk_compare_report.json。

用法:
  py -3 compare_apk_deep.py
  py -3 compare_apk_deep.py path/kr.apk path/cn.apk
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
DEFAULT_KR = ROOT / "com.epidgames.trickcalrevive.base.apk"
DEFAULT_CN = ROOT / "ddlezj_1.4.0_13029_20260512_054636_021a9.apk"
OUT = ROOT / "apk_compare_report.json"

KO_RE = re.compile(
    r"[\uAC00-\uD7AF][\uAC00-\uD7AF\s\d\.,!?·…「」『』（）:;]{2,80}"
)
ZH_RE = re.compile(
    r"[\u4e00-\u9fff][\u4e00-\u9fff\s\d\.,!?·…「」『』（）:;，。！？、]{2,120}"
)
META = "assets/bin/Data/Managed/Metadata/global-metadata.dat"

KEYWORDS = [
    b"StringTable", b"TableData", b"Localization", b"GetString",
    b"TextData", b"LanguageManager", b"dic", b"ATG_E", b"libData",
    b"copyDataToAsset", b"sharedassets0", b"TextAsset",
]


def find_apks(kr_arg: str | None, cn_arg: str | None) -> tuple[Path, Path]:
    kr = Path(kr_arg) if kr_arg else DEFAULT_KR
    cn = Path(cn_arg) if cn_arg else DEFAULT_CN
    if not kr.is_file():
        raise FileNotFoundError(f"韩版 APK 不存在: {kr}")
    if not cn.is_file():
        raise FileNotFoundError(f"国服 APK 不存在: {cn}")
    return kr, cn


def index_apk(path: Path) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            data = z.read(info.filename)
            out[info.filename] = (info.file_size, hashlib.md5(data).hexdigest())
    return out


def scan_metadata_strings(z: zipfile.ZipFile) -> dict[str, list[str]]:
    if META not in z.namelist():
        return {"ko": [], "zh": []}
    text = z.read(META).decode("utf-8", errors="ignore")
    ko, zh = set(), set()
    for m in KO_RE.finditer(text):
        s = m.group().strip()
        if sum(1 for c in s if "\uAC00" <= c <= "\uD7AF") >= 2:
            ko.add(s)
    for m in ZH_RE.finditer(text):
        s = m.group().strip()
        if sum(1 for c in s if "\u4e00" <= c <= "\u9fff") >= 2:
            zh.add(s)
    return {"ko": sorted(ko), "zh": sorted(zh)}


def scan_cn_split_sample(z: zipfile.ZipFile, max_splits: int = 8) -> dict:
    splits = sorted(n for n in z.namelist() if "sharedassets0.assets.split" in n)
    ko_utf8, zh_utf8 = set(), set()
    ko_utf16, zh_utf16 = set(), set()
    for name in splits[:max_splits]:
        data = z.read(name)
        t8 = data.decode("utf-8", errors="ignore")
        for m in KO_RE.finditer(t8):
            ko_utf8.add(m.group().strip())
        for m in ZH_RE.finditer(t8):
            zh_utf8.add(m.group().strip())
        t16 = data.decode("utf-16-le", errors="ignore")
        for m in re.finditer(r"[\uAC00-\uD7AF]{3,40}", t16):
            ko_utf16.add(m.group())
        for m in re.finditer(r"[\u4e00-\u9fff]{4,80}", t16):
            zh_utf16.add(m.group())
    return {
        "split_count": len(splits),
        "sampled": min(max_splits, len(splits)),
        "ko_utf8": len(ko_utf8),
        "zh_utf8": len(zh_utf8),
        "ko_utf16": len(ko_utf16),
        "zh_utf16": len(zh_utf16),
    }


def keyword_hits(path: Path) -> dict[str, int]:
    raw = path.read_bytes()
    return {kw.decode("ascii", errors="replace"): raw.count(kw) for kw in KEYWORDS}


def main() -> None:
    kr_path, cn_path = find_apks(
        sys.argv[1] if len(sys.argv) > 1 else None,
        sys.argv[2] if len(sys.argv) > 2 else None,
    )
    kr_idx = index_apk(kr_path)
    cn_idx = index_apk(cn_path)
    kr_names, cn_names = set(kr_idx), set(cn_idx)
    common = kr_names & cn_names
    same_hash = [n for n in common if kr_idx[n] == cn_idx[n]]

    with zipfile.ZipFile(kr_path) as kr_z, zipfile.ZipFile(cn_path) as cn_z:
        kr_meta = scan_metadata_strings(kr_z)
        cn_meta = scan_metadata_strings(cn_z)
        cn_splits = scan_cn_split_sample(cn_z)

    meta_ko_both = sorted(set(kr_meta["ko"]) & set(cn_meta["ko"]))
    diff_paths = []
    for n in sorted(common):
        ks, kh = kr_idx[n]
        cs, ch = cn_idx[n]
        if kh != ch:
            diff_paths.append({
                "path": n,
                "kr_size": ks,
                "cn_size": cs,
                "note": "hash_diff",
            })

    report = {
        "kr_apk": kr_path.name,
        "cn_apk": cn_path.name,
        "summary": {
            "kr_entries": len(kr_names),
            "cn_entries": len(cn_names),
            "common_paths": len(common),
            "identical_files": len(same_hash),
            "kr_only": len(kr_names - cn_names),
            "cn_only": len(cn_names - kr_names),
            "localization_strategy": {
                "kr": "assets/dic + ATG_E.sec 加密，运行时解密（sharedassets split 无明文）",
                "cn": "sharedassets0.assets.split* 明文繁中，无 dic/libData",
            },
        },
        "metadata_strings": {
            "kr_ko_count": len(kr_meta["ko"]),
            "kr_zh_count": len(kr_meta["zh"]),
            "cn_ko_count": len(cn_meta["ko"]),
            "cn_zh_count": len(cn_meta["zh"]),
            "ko_in_both_metadata": meta_ko_both,
        },
        "cn_sharedassets_sample": cn_splits,
        "keyword_hits": {
            "kr": keyword_hits(kr_path),
            "cn": keyword_hits(cn_path),
        },
        "important_kr_only": sorted(
            n for n in kr_names - cn_names
            if any(k in n for k in ("dic", "ATG", "libData", "ATG_E"))
        ),
        "important_cn_only": sorted(
            n for n in cn_names - kr_names
            if "sharedassets0.assets.split" in n
        )[:20],
        "common_but_different": [
            d for d in diff_paths
            if any(k in d["path"] for k in ("global-metadata", "ScriptingAssemblies", "boot.config"))
        ],
        "recommendations": [
            "静态 APK 无法建立可靠韩中逐条表；国服 split 与韩版 dic 存储路径不同。",
            "优先 Frida Hook 抓运行时韩文明文，再与国服文本池配对。",
            "metadata 中两服共有韩文极少，不宜作为对照主来源。",
            "国服 sharedassets 明文繁中已用于 game_strings_zh.json 模糊纠错。",
        ],
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT.name}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"metadata 共有韩文: {meta_ko_both}")
    print(f"国服 split 文件数: {cn_splits['split_count']}")


if __name__ == "__main__":
    main()
