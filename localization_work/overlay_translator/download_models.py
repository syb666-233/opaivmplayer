"""预下载 EasyOCR 韩文模型（避免首次启动卡在 GitHub）。"""
from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

# 韩文 OCR 需要的两个模型
MODELS = (
    {
        "name": "检测模型 craft_mlt_25k",
        "filename": "craft_mlt_25k.pth",
        "zip_name": "craft_mlt_25k.zip",
        "md5": "2f8227d2def4037cdb3b34389dcf9ec1",
        "urls": (
            "https://ghfast.top/https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
            "https://mirror.ghproxy.com/https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
        ),
    },
    {
        "name": "韩文识别模型 korean_g2",
        "filename": "korean_g2.pth",
        "zip_name": "korean_g2.zip",
        "md5": "befecf7b1ca2fffb5af814a51443682d",
        "urls": (
            "https://ghfast.top/https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/korean_g2.zip",
            "https://mirror.ghproxy.com/https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/korean_g2.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/korean_g2.zip",
        ),
    },
)


def model_dir() -> Path:
    d = Path(os.path.expanduser("~/.EasyOCR/model"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        chunk_size = 256 * 1024
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total > 0:
                    pct = done * 100 // total
                    mb = done / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    print(f"\r  进度: {pct}% ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
        print(flush=True)


def ensure_model(spec: dict) -> bool:
    out = model_dir() / spec["filename"]
    if out.is_file() and md5_file(out) == spec["md5"]:
        print(f"[OK] 已存在: {spec['filename']}")
        return True

    print(f"\n[下载] {spec['name']} -> {out.name}")
    zip_path = model_dir() / spec["zip_name"]

    for url in spec["urls"]:
        try:
            print(f"  尝试: {url[:70]}...")
            download(url, zip_path)
            break
        except Exception as exc:
            print(f"  失败: {exc}")
            if zip_path.exists():
                zip_path.unlink()
    else:
        print(f"[ERROR] 无法下载 {spec['filename']}")
        return False

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extract(spec["filename"], model_dir())
    finally:
        if zip_path.exists():
            zip_path.unlink()

    if not out.is_file() or md5_file(out) != spec["md5"]:
        print(f"[ERROR] {spec['filename']} MD5 校验失败")
        if out.exists():
            out.unlink()
        return False

    print(f"[OK] {spec['filename']} 下载完成")
    return True


def models_ready() -> bool:
    d = model_dir()
    return all((d / m["filename"]).is_file() for m in MODELS)


def main() -> int:
    print("=" * 50)
    print(" EasyOCR 韩文模型预下载")
    print(f" 目录: {model_dir()}")
    print("=" * 50)

    ok = all(ensure_model(m) for m in MODELS)
    if ok:
        print("\n全部模型就绪，可以运行 start.bat")
        return 0
    print("\n下载失败。请检查网络，或开 VPN 后重试本脚本。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
