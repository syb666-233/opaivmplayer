"""
打包 LunaTrickcal 正式版 zip（面向普通用户）。

用法:
  py -3 scripts/build_release.py
  py -3 scripts/build_release.py --version 1.0.0
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"
DOCS = ROOT / "docs" / "release"
DEFAULT_VERSION = "1.0.0"

PKG_PREFIX = "LunaTrickcal"

RUNTIME_EXCLUDE_DIRS = {"cache", "__pycache__", ".git"}
RUNTIME_EXCLUDE_FILES = {"trickcal_overlay.log", "trickcal_auto_scan.py"}

RELEASE_ROOT_FILES = [
    "start_trickcal_luna.vbs",
    "start_trickcal_luna.bat",
    "导出学习词典.bat",
]

RELEASE_DOC_FILES = [
    "使用说明.txt",
    "快速入门.txt",
    "常见问题FAQ.txt",
    "版本说明.txt",
    "README-正式版.txt",
]

RELEASE_SCRIPT_FILES = [
    "scripts/start_luna.vbs",
    "scripts/launch_luna.ps1",
]

# 正式版标识（写入 zip 文件名）
RELEASE_LABEL = "正式版"


def _should_skip_runtime(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in RUNTIME_EXCLUDE_DIRS:
        return True
    if rel.name in RUNTIME_EXCLUDE_FILES:
        return True
    return False


def _copy_runtime(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if _should_skip_runtime(rel):
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _sanitize_userconfig(runtime: Path) -> None:
    uc = runtime / "userconfig"
    save = uc / "savegamedata_5.3.1.json"
    save.write_text(
        json.dumps(
            [[], {}, [None, 1], None, {"localedpath": {}, "imagefrom": {}}],
            ensure_ascii=False,
            indent=4,
        ),
        encoding="utf-8",
    )
    learn_cfg = uc / "trickcal_learn_config.json"
    if not learn_cfg.is_file():
        learn_cfg.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "min_repeats": 3,
                    "min_ko_len": 2,
                    "max_ko_len": 120,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    src_mp = ROOT.parent / "luna_integration" / "myprocess_trickcal.py"
    if src_mp.is_file():
        shutil.copy2(src_mp, uc / "myprocess.py")

    cfg_path = uc / "config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for k in list(cfg.keys()):
            if k.startswith("trickcal_auto_scan"):
                cfg.pop(k, None)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    data = runtime / "data"
    for name in ("learned_pairs.json", "learned_pairs.jsonl"):
        p = data / name
        if p.is_file():
            p.unlink()
    (data / "learned_pairs.json").write_text(
        json.dumps({"version": 1, "count": 0, "pairs": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_manual(staging: Path, version: str) -> None:
    text = f"""LunaTrickcal v{version} {RELEASE_LABEL} — 使用说明
{'=' * 56}

Trickcal Revive（韩版）韩语 OCR 实时翻译工具
适用：OurPlay / 云手机 / 模拟器 + Windows 10/11

【请先阅读】快速入门.txt — 5 分钟上手步骤

一、安装与启动
--------------
1. 解压 zip 到任意目录（路径尽量不含中文空格）
2. 双击 start_trickcal_luna.vbs 启动 Luna
3. 首次运行若弹出 Warning，点「是」即可

二、基本使用流程
----------------
  启动 Luna → 游戏管理添加 op.exe → 绑定窗口 → 框选韩文区域 → 按 4 翻译

详细步骤：
  1. 打开 OurPlay，进入 Trickcal 游戏
  2. Luna 翻译条 →「游戏管理」→ 添加游戏 → 选择 op.exe 路径
  3. 点击「绑定窗口」→ 点击游戏画面
  4. 点击「选取 OCR 范围」→ 拖选含韩文的区域
  5. 按键盘 4 → OCR 识别并翻译，黄色浮层显示在选区旁

三、快捷键
----------
  4  — 单次 OCR + 翻译（推荐，每个区域用一次）
  6  — 删除单个 OCR 区域 / 浮层（框选或右键浮层）
  3  — 清除全部 OCR 区域与浮层

四、翻译优化（已预装）
--------------------
  · 39 条 Trickcal UI 专有名词（商店、招募、使徒等）
  · 12 万+ 国服中文文本池（自动纠正机翻偏差）
  · 运行时自动学习：同一韩文多次出现且译文一致 → 写入本地词典
    数据文件：runtime\\data\\learned_pairs.json
    开关：runtime\\userconfig\\trickcal_learn_config.json

  手动编辑专有名词：
    游戏管理 → 右键游戏 → 游戏设置 → 翻译优化 → 专有名词翻译

五、性能建议
------------
  · 翻译引擎只保留 Bing（关闭多余引擎）
  · OCR 执行周期 ≥ 4 秒（设置 → 文本输入 → OCR）
  · 避免同时开多个 OCR 持续模式

六、导出与分享词典
------------------
  双击「导出学习词典.bat」→ 桌面生成 trickcal_learned_export.json

七、常见问题
------------
  见 常见问题FAQ.txt

八、版本信息
------------
  见 版本说明.txt

许可：基于 LunaTranslator（GPLv3），详见 runtime\\LICENSES\\
构建：{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
"""
    (staging / "使用说明.txt").write_text(text, encoding="utf-8")

    readme = f"""LunaTrickcal v{version} {RELEASE_LABEL}
========================

Trickcal Revive 韩版 · 韩语 OCR 翻译 · 正式发行包

【从这里开始】
  1. 快速入门.txt
  2. 使用说明.txt
  3. 常见问题FAQ.txt

【启动】start_trickcal_luna.vbs

【标识】本 zip 为正式版（Stable），不含实验性全窗自动 OCR 功能。
"""
    (staging / "README-正式版.txt").write_text(readme, encoding="utf-8")

    for name in ("快速入门.txt", "常见问题FAQ.txt", "版本说明.txt"):
        src = DOCS / name
        if src.is_file():
            shutil.copy2(src, staging / name)


def _write_export_bat(staging: Path) -> None:
    bat = """@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "SRC=runtime\\data\\learned_pairs.json"
set "DST=%USERPROFILE%\\Desktop\\trickcal_learned_export.json"
if not exist "%SRC%" (
  echo [错误] 未找到学习词典: %SRC%
  pause
  exit /b 1
)
copy /Y "%SRC%" "%DST%" >nul
echo [OK] 已导出到桌面:
echo   %DST%
pause
"""
    (staging / "导出学习词典.bat").write_text(bat, encoding="utf-8")


def build(version: str) -> Path:
    pkg_name = f"{PKG_PREFIX}-v{version}-{RELEASE_LABEL}-win64"
    staging = DIST / pkg_name
    zip_path = DIST / f"{pkg_name}.zip"

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    print(f"[1/6] 复制 runtime …")
    _copy_runtime(ROOT / "runtime", staging / "runtime")

    print(f"[2/6] 清理用户配置 …")
    _sanitize_userconfig(staging / "runtime")

    print(f"[3/6] 复制启动脚本 …")
    for name in RELEASE_ROOT_FILES:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, staging / name)
    for rel in RELEASE_SCRIPT_FILES:
        src = ROOT / rel
        if src.is_file():
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    print(f"[4/6] 生成用户文档 …")
    _write_manual(staging, version)
    _write_export_bat(staging)

    print(f"[5/6] 写入发行标识 …")
    (staging / f"【{RELEASE_LABEL}】请勿与测试版混用.txt").write_text(
        f"本包为 LunaTrickcal v{version} {RELEASE_LABEL}\n"
        f"文件名: {zip_path.name}\n"
        f"构建时间: {datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )

    print(f"[6/6] 压缩 zip …")
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in staging.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(staging.parent))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\n[完成] {zip_path}")
    print(f"       大小: {size_mb:.1f} MB")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    args = ap.parse_args()
    if not (ROOT / "runtime" / "LunaTranslator.exe").is_file():
        print("[错误] 未找到 runtime/LunaTranslator.exe，请先运行 setup_trickcal_luna.bat")
        return 1
    build(args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
