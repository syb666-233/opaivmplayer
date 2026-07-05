"""
扫描国服 Trickcal APK，提取可读中文并探测文本资源结构。
用法：将国服 base.apk 放入 localization_work/ 后运行:
  py -3 analyze_cn_apk.py
  py -3 analyze_cn_apk.py path/to/cn.apk
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent

# 简体 + 常用标点
ZH_RE = re.compile(
    r"[\u4e00-\u9fff][\u4e00-\u9fff\s\d\.,!?·…「」『』（）:;，。！？、—\-]{2,120}"
)
KO_RE = re.compile(
    r"[\uAC00-\uD7AF][\uAC00-\uD7AF\s\d\.,!?·…「」『』（）:;]{2,80}"
)

KEYWORDS = [
    b"dic", b"libData", b"Decrypt", b"ATG", b"Localization", b"StringTable",
    b"Language", b"Locale", b"zh", b"CN", b"chinese", b"TextAsset", b"TableData",
]


def find_apk(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(p)
        return p
    candidates = sorted(ROOT.glob("*.apk"), key=lambda x: -x.stat().st_size)
    # 优先文件名含 cn / china / 国服 / trickcal
    prefer = [
        p for p in candidates
        if any(k in p.name.lower() for k in ("cn", "china", "国服", "trickcal", "epid"))
    ]
    pool = prefer or candidates
    if not pool:
        raise FileNotFoundError(f"未在 {ROOT} 找到 .apk，请将国服 APK 放入该目录")
    return pool[0]


def scan_zip_strings(z: zipfile.ZipFile, pattern: re.Pattern, label: str) -> set[str]:
    found: set[str] = set()
    for info in z.infolist():
        if info.file_size > 80_000_000 or info.is_dir():
            continue
        if not info.filename.startswith("assets/"):
            continue
        try:
            data = z.read(info.filename)
        except Exception:
            continue
        text = data.decode("utf-8", errors="ignore")
        for m in pattern.findall(text):
            s = m.strip()
            if len(s) >= 3:
                found.add(s)
    print(f"  {label} (assets utf-8 扫描): {len(found)} 条")
    return found


def preview_dic(z: zipfile.ZipFile) -> None:
    dic_files = [n for n in z.namelist() if "dic" in n.lower() and not n.endswith("/")]
    print(f"\n=== dic 相关文件 ({len(dic_files)}) ===")
    for n in sorted(dic_files)[:20]:
        info = z.getinfo(n)
        data = z.read(n)
        magic = data[:16].hex() if len(data) >= 16 else data.hex()
        print(f"  {info.file_size:>10}  {n}  magic={magic[:32]}...")
        if info.file_size < 8000:
            sample = data.decode("utf-8", errors="replace")[:400]
            if any("\u4e00" <= c <= "\u9fff" for c in sample):
                print(f"    [含中文明文] {sample[:200]}")


def keyword_hits(raw: bytes) -> None:
    print("\n=== 关键字命中 ===")
    for kw in KEYWORDS:
        c = raw.count(kw)
        if c:
            print(f"  {kw.decode('ascii', errors='replace')}: {c}")


def main() -> None:
    apk_path = find_apk(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"分析 APK: {apk_path.name} ({apk_path.stat().st_size // 1024 // 1024} MB)\n")

    z = zipfile.ZipFile(apk_path)
    names = z.namelist()
    assets = [n for n in names if n.startswith("assets/") and not n.endswith("/")]
    print(f"条目: {len(names)}, assets: {len(assets)}")

    preview_dic(z)

    zh = scan_zip_strings(z, ZH_RE, "中文")
    ko = scan_zip_strings(z, KO_RE, "韩文")

    # global-metadata
    meta_path = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
    if meta_path in names:
        meta = z.read(meta_path).decode("utf-8", errors="ignore")
        meta_zh = set(ZH_RE.findall(meta))
        meta_ko = set(KO_RE.findall(meta))
        print(f"  metadata 中文: {len(meta_zh)}, 韩文: {len(meta_ko)}")

    keyword_hits(apk_path.read_bytes())

    out_zh = ROOT / "cn_strings_raw.txt"
    out_ko = ROOT / "cn_apk_korean_fragments.txt"
    quality = [
        s for s in zh
        if sum(1 for c in s if "\u4e00" <= c <= "\u9fff") >= max(2, len(s) // 3)
        and not re.search(r"[\u0080-\u00ff]{4,}", s)
    ]
    out_zh.write_text("\n".join(sorted(quality, key=len)), encoding="utf-8")
    out_ko.write_text("\n".join(sorted(ko, key=len)[:5000]), encoding="utf-8")

    print(f"\n已写入: {out_zh.name} ({len(quality)} 条可读中文)")
    print(f"已写入: {out_ko.name} ({min(len(ko), 5000)} 条韩文片段)")
    print("\n样本中文:")
    for s in sorted(quality, key=len, reverse=True)[:15]:
        print(f"  {s[:80]}")

    if len(quality) < 50:
        print(
            "\n⚠ 明文中文很少，文本可能在 assets/dic 加密内。"
            "下一步需对比 libData.so / ATG 解密逻辑（与韩版相同管线）。"
        )
    else:
        print("\n✓ 明文中文充足，可直接构建 OCR→词典 模糊匹配表。")


if __name__ == "__main__":
    main()
