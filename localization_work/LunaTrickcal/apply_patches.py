"""
Apply Trickcal patches to a Luna runtime copy (does not touch original LunaTranslator_x64).

Creates/updates: LunaTrickcal/runtime/  (copy of LunaTranslator_x64 + patches)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
SRC_LUNA = WORK / "LunaTranslator_x64"
RUNTIME = HERE / "runtime"
PATCHES = HERE / "patches"
HOOK_MARKER = "# TRICKCAL_PLUGIN_INSTALL"
HOOK_CODE = """
        try:
            import trickcal_plugin
            trickcal_plugin.install(self)
        except Exception:
            from traceback import print_exc
            print_exc()
"""


def copy_runtime() -> None:
    if not SRC_LUNA.is_dir():
        raise FileNotFoundError(f"Missing {SRC_LUNA}")
    if RUNTIME.is_dir():
        print(f"Runtime exists: {RUNTIME} (skip full copy)")
        return
    print(f"Copying {SRC_LUNA.name} -> runtime/ ...")
    shutil.copytree(SRC_LUNA, RUNTIME)


def apply_tree() -> None:
    for src in PATCHES.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(PATCHES)
        if rel.parts[0] == "userconfig":
            dst = RUNTIME / rel
        elif rel.name.endswith(".py") and len(rel.parts) == 1:
            dst = RUNTIME / "LunaTranslator" / rel.name
        else:
            dst = RUNTIME / "LunaTranslator" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  patch: {rel}")


def patch_luna_translator_py() -> None:
    path = RUNTIME / "LunaTranslator" / "LunaTranslator.py"
    text = path.read_text(encoding="utf-8")

    # Remove legacy hook placed after mainuiloadafter()
    legacy = f"        self.mainuiloadafter()\n{HOOK_MARKER}\n{HOOK_CODE}        startgame(startwithgameuid)"
    plain = "        self.mainuiloadafter()\n        startgame(startwithgameuid)"
    if legacy in text:
        text = text.replace(legacy, plain, 1)
        print("  removed legacy hook (was after mainuiloadafter)")

    target = (
        "        self.translation_ui.aftershowdosomething()\n        self.mainuiloadafter()"
    )
    desired = (
        f"        self.translation_ui.aftershowdosomething()\n{HOOK_MARKER}\n{HOOK_CODE}        self.mainuiloadafter()"
    )

    if HOOK_MARKER in text and desired in text:
        print("  LunaTranslator.py hook OK (before mainuiloadafter)")
    elif target in text:
        text = text.replace(target, desired, 1)
        print("  hooked LunaTranslator.loadui (before mainuiloadafter)")
    else:
        raise RuntimeError("LunaTranslator.py hook point not found; update patch script")

    path.write_text(text, encoding="utf-8")


def merge_userconfig() -> None:
    cfg_path = RUNTIME / "userconfig" / "config.json"
    default = RUNTIME / "LunaTranslator" / "defaultconfig" / "config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    elif default.is_file():
        cfg = json.loads(default.read_text(encoding="utf-8"))
    else:
        cfg = {}
    opt = cfg.setdefault("transoptimi", {})
    opt["noundict"] = True
    opt["myprocess"] = True
    cfg["trickcal_overlay_enable"] = True
    cfg.setdefault("multiregion", True)
    cfg.setdefault("trickcal_overlay_clickthrough", False)
    cfg.setdefault("trickcal_overlay_font_size", 16)
    cfg.setdefault("trickcal_translate_on_range_select", False)
    cfg.setdefault("trickcal_overlay_offsets", {})
    cfg.setdefault("autorun", True)
    if float(cfg.get("ocr_interval", 1.5)) < 3.5:
        cfg["ocr_interval"] = 4.0
    if int(cfg.get("ocr_text_diff", 3)) < 8:
        cfg["ocr_text_diff"] = 8
    delete_hk = "trickcal_delete_region"
    quick_keys = cfg.setdefault("myquickkeys", [])
    if delete_hk not in quick_keys:
        quick_keys.append(delete_hk)
    quick_all = cfg.setdefault("quick_setting", {}).setdefault("all", {})
    quick_all[delete_hk] = {
        "use": True,
        "name": "删除单个OCR区域",
        "keystring": "6",
    }
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  merged userconfig/config.json presets")

    hk_dir = RUNTIME / "userconfig" / "myhotkeys"
    hk_dir.mkdir(parents=True, exist_ok=True)
    src_hk = PATCHES / "userconfig" / "myhotkeys" / "trickcal_batch_ocr.py"
    if src_hk.is_file():
        shutil.copy2(src_hk, hk_dir / src_hk.name)
    src_del = PATCHES / "userconfig" / "myhotkeys" / "trickcal_delete_region.py"
    if src_del.is_file():
        shutil.copy2(src_del, hk_dir / src_del.name)


def restore_signed_exe() -> None:
    """Keep launcher exes identical to upstream; never patch them (breaks signature)."""
    for name in ("LunaTranslator.exe", "LunaTranslator_admin.exe"):
        src = SRC_LUNA / name
        dst = RUNTIME / name
        if not src.is_file():
            continue
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            print(f"  signed exe OK: {name}")
        else:
            shutil.copy2(src, dst)
            print(f"  restored signed exe: {name}")


def main() -> None:
    copy_runtime()
    apply_tree()
    patch_luna_translator_py()
    merge_userconfig()
    restore_signed_exe()
    print(f"\nDone. Start: {HERE / 'start_trickcal_luna.bat'}")


if __name__ == "__main__":
    main()
