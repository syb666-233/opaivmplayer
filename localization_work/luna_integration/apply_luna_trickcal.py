"""
将 Trickcal 词典 / Prompt / 游戏专属配置写入 Luna userconfig。

用法:
  py -3 apply_luna_trickcal.py
  py -3 apply_luna_trickcal.py --luna-root path/to/runtime
  py -3 apply_luna_trickcal.py --json-log   # 输出机器可读摘要
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
NOUDICT = HERE / "trickcal_noundict.json"
MYPROCESS_SRC = HERE / "myprocess_trickcal.py"
KO_ZH_SRC = WORK / "overlay_translator" / "ko_zh_pairs.json"
GAME_STRINGS_SRC = WORK / "overlay_translator" / "game_strings_zh.json"

TRICKCAL_GAME_KEYWORDS = (
    "trickcal",
    "epidgames",
    "트릭컬",
    "com.epidgames.trickcalrevive",
    "ourplay",
    "op.exe",
    "穿越异世界",
    "恶作剧",
)

# 大模型 Prompt（韩语 → 简中 + DictWithPrompt）
TRICKCAL_SYS_PROMPT = (
    "你是韩语手游《Trickcal Revive》（트릭컬 리바이브）的翻译助手。"
    "将用户给出的韩语游戏文本翻译成自然流畅的简体中文。"
    "保留 UI 菜单的简洁风格；剧情对话保留语气与情感。"
    "不要输出解释、括号注释或原文。"
)

TRICKCAL_USER_PROMPT = (
    "{DictWithPrompt[翻译时请严格使用以下 Trickcal 专有名词对照，不要自行改写：]}\n"
    "请翻译以下韩语：\n{sentence}"
)

LLM_TRANSLATOR_KEYS = (
    "chatgpt-3rd-party",
)


def find_luna_root(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not (p / "LunaTranslator.exe").is_file():
            raise FileNotFoundError(f"未找到 LunaTranslator.exe: {p}")
        return p
    for c in (
        WORK / "LunaTrickcal" / "runtime",
        WORK / "LunaTranslator_x64",
        WORK / "LunaTranslator" / "LunaTranslator_x64_win10",
    ):
        if (c / "LunaTranslator.exe").is_file():
            return c
    raise FileNotFoundError(
        "未找到 LunaTranslator.exe，请解压 LunaTranslator_x64_win10.zip 或先运行 LunaTrickcal/setup"
    )


def load_config(luna: Path) -> dict:
    user = luna / "userconfig" / "config.json"
    default = luna / "LunaTranslator" / "defaultconfig" / "config.json"
    if user.is_file():
        return json.loads(user.read_text(encoding="utf-8"))
    if default.is_file():
        return json.loads(default.read_text(encoding="utf-8"))
    return {}


def _compact(s: str) -> str:
    return "".join((s or "").split())


def merge_noundict(cfg: dict, entries: list[dict]) -> tuple[int, int]:
    existing = cfg.get("noundictconfig_ex") or []
    if not isinstance(existing, list):
        existing = []
    by_src = {_compact(e.get("src", "")): e for e in existing if isinstance(e, dict)}
    added = 0
    for e in entries:
        src = e.get("src", "")
        if not src:
            continue
        key = _compact(src)
        item = {"src": src, "dst": e.get("dst", ""), "info": e.get("info", "trickcal")}
        if key in by_src:
            by_src[key] = item
        else:
            by_src[key] = item
            added += 1
    merged = sorted(by_src.values(), key=lambda x: len(_compact(x.get("src", ""))), reverse=True)
    cfg["noundictconfig_ex"] = merged
    return added, len(merged)


def apply_preset(cfg: dict) -> None:
    opt = cfg.setdefault("transoptimi", {})
    opt["noundict"] = True
    opt["myprocess"] = True

    sources = cfg.setdefault("sourcestatus2", {})
    ocr = sources.setdefault("ocr", {})
    ocr["use"] = True
    hook = sources.setdefault("texthook", {})
    hook["use"] = False

    cfg.setdefault("ocr", {})["local"] = cfg.get("ocr", {}).get("local") or {"use": True}

    for key in list(cfg.keys()):
        if key.startswith("srclang") and not key.endswith("4"):
            cfg[key] = "ko"
        if key.startswith("tgtlang") and not key.endswith("4"):
            cfg[key] = "zh"


def apply_dict_with_prompt(luna: Path) -> dict:
    """优化 2：为大模型翻译器启用 DictWithPrompt 自定义 Prompt。"""
    ts_path = luna / "userconfig" / "translatorsetting.json"
    default_ts = luna / "LunaTranslator" / "defaultconfig" / "translatorsetting.json"
    if ts_path.is_file():
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
    elif default_ts.is_file():
        ts = json.loads(default_ts.read_text(encoding="utf-8"))
    else:
        ts = {}

    updated = []
    for key in LLM_TRANSLATOR_KEYS:
        block = ts.setdefault(key, {})
        args = block.setdefault("args", {})
        args["使用自定义promt"] = True
        args["自定义promt"] = TRICKCAL_SYS_PROMPT
        args["use_user_user_prompt"] = True
        args["user_user_prompt"] = TRICKCAL_USER_PROMPT
        updated.append(key)

    ts_path.parent.mkdir(parents=True, exist_ok=True)
    ts_path.write_text(json.dumps(ts, ensure_ascii=False, indent=4), encoding="utf-8")
    return {"updated_translators": updated, "path": str(ts_path)}


def _is_trickcal_game(entry: dict) -> bool:
    blob = " ".join(
        str(entry.get(k, "") or "")
        for k in ("title", "gamepath", "launchpath", "exepath", "path")
    ).lower()
    return any(kw.lower() in blob for kw in TRICKCAL_GAME_KEYWORDS)


def apply_game_private_noundict(luna: Path, entries: list[dict]) -> dict:
    """优化 3：写入游戏专属专有名词（savegamedata 内 Trickcal 条目）。"""
    userconfig = luna / "userconfig"
    matched_uids: list[str] = []
    files_touched: list[str] = []

    for sg_path in sorted(userconfig.glob("savegamedata*.json")):
        try:
            data = json.loads(sg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list) or len(data) < 2:
            continue
        save_list = data[0]
        save_data = data[1]
        if not isinstance(save_data, dict):
            continue

        changed = False
        for uid, entry in save_data.items():
            if not isinstance(entry, dict):
                continue
            if not _is_trickcal_game(entry):
                continue

            by_src = {
                _compact(e.get("src", "")): e
                for e in entry.get("noundictconfig_ex") or []
                if isinstance(e, dict)
            }
            for e in entries:
                src = e.get("src", "")
                if not src:
                    continue
                by_src[_compact(src)] = {
                    "src": src,
                    "dst": e.get("dst", ""),
                    "info": e.get("info", "trickcal"),
                }
            entry["noundictconfig_ex"] = sorted(
                by_src.values(), key=lambda x: len(_compact(x.get("src", ""))), reverse=True
            )
            entry["noundict_use"] = True
            entry["noundict_merge"] = True
            entry["transoptimi_followdefault"] = False
            entry["myprocess_use"] = True
            matched_uids.append(str(uid))
            changed = True

        if changed:
            sg_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            files_touched.append(sg_path.name)

    # 无绑定游戏时，写入待应用模板（下次 sync 时自动合并）
    pending = {
        "version": 1,
        "note": "Luna 绑定 Trickcal 窗口后，再次运行 sync_dict_and_patch.bat 将自动写入游戏专属词典",
        "keywords": list(TRICKCAL_GAME_KEYWORDS),
        "game_settings": {
            "noundict_use": True,
            "noundict_merge": True,
            "transoptimi_followdefault": False,
            "myprocess_use": True,
        },
        "entries": entries,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    pending_path = userconfig / "trickcal_game_noundict_pending.json"
    pending_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "matched_game_uids": matched_uids,
        "savegamedata_files": files_touched,
        "pending_template": str(pending_path.name),
        "pending_note": "无匹配游戏时使用 pending 模板，绑定后重跑 sync",
    }


def sync_data_files(luna: Path) -> dict:
    """将 ko_zh_pairs / game_strings 同步到 runtime/data/ 供 myprocess 读取。"""
    data_dir = luna / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src, name in (
        (KO_ZH_SRC, "ko_zh_pairs.json"),
        (GAME_STRINGS_SRC, "game_strings_zh.json"),
        (NOUDICT, "trickcal_noundict.json"),
    ):
        if not src.is_file():
            continue
        dst = data_dir / name
        shutil.copy2(src, dst)
        copied.append(name)
    return {"data_dir": str(data_dir), "copied": copied}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--luna-root", type=str, default=None)
    ap.add_argument("--skip-myprocess", action="store_true")
    ap.add_argument("--skip-dwp", action="store_true", help="跳过 DictWithPrompt 配置")
    ap.add_argument("--skip-game-private", action="store_true", help="跳过游戏专属词典")
    ap.add_argument("--json-log", action="store_true")
    args = ap.parse_args()

    if not NOUDICT.is_file():
        raise SystemExit(f"请先运行 export_luna_glossary.py 生成 {NOUDICT.name}")

    luna = find_luna_root(args.luna_root)
    data = json.loads(NOUDICT.read_text(encoding="utf-8"))
    entries = data.get("entries") or []

    cfg = load_config(luna)
    added, total = merge_noundict(cfg, entries)
    apply_preset(cfg)

    user_dir = luna / "userconfig"
    user_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = user_dir / "config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict = {
        "luna_root": str(luna),
        "noundict_total": total,
        "noundict_added": added,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not args.skip_myprocess and MYPROCESS_SRC.is_file():
        dst = user_dir / "myprocess.py"
        shutil.copy2(MYPROCESS_SRC, dst)
        report["myprocess"] = str(dst)

    report["data_sync"] = sync_data_files(luna)

    if not args.skip_dwp:
        report["dict_with_prompt"] = apply_dict_with_prompt(luna)

    if not args.skip_game_private:
        report["game_private_noundict"] = apply_game_private_noundict(luna, entries)

    if args.json_log:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Luna 目录: {luna}")
        print(f"专有名词(全局): {total} 条 (本次新增约 {added} 条)")
        print(f"数据文件: {report['data_sync']['copied']}")
        if report.get("dict_with_prompt"):
            print(f"DictWithPrompt: {report['dict_with_prompt']['updated_translators']}")
        gp = report.get("game_private_noundict", {})
        if gp.get("matched_game_uids"):
            print(f"游戏专属词典: 已写入 uid {gp['matched_game_uids']}")
        else:
            print(f"游戏专属词典: 暂无绑定 → {gp.get('pending_template')}")
        print("已启用: noundict + myprocess + OCR 韩→简中 preset")


if __name__ == "__main__":
    main()
