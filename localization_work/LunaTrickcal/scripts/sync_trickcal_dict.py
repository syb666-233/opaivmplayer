"""
Trickcal 词典同步全流程（优化 1）：
  1. 合并 contributions/ 外部词条
  2. build_ko_zh_pairs（Frida 抓取 + 国服文本池）
  3. export_luna_glossary
  4. apply_luna_trickcal → LunaTrickcal/runtime
  5. 写入 sync_log.json 供查阅

用法:
  py -3 scripts/sync_trickcal_dict.py
  py -3 scripts/sync_trickcal_dict.py --no-mt
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
LUNA_TRICKCAL = HERE.parent
WORK = LUNA_TRICKCAL.parent
LOG_PATH = LUNA_TRICKCAL / "logs" / "sync_log.json"


def _run(cmd: list[str], cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "cmd": cmd,
        "cwd": str(cwd) if cwd else None,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:] if proc.stdout else "",
        "stderr": proc.stderr[-2000:] if proc.stderr else "",
        "ok": proc.returncode == 0,
    }


def append_log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if LOG_PATH.is_file():
        try:
            history = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = []
    if not isinstance(history, list):
        history = []
    history.append(entry)
    if len(history) > 50:
        history = history[-50:]
    LOG_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mt", action="store_true", help="build_ko_zh_pairs 不调用 Bing")
    ap.add_argument("--skip-contrib", action="store_true")
    ap.add_argument("--with-patches", action="store_true", help="同时运行 apply_patches.py（需先关闭 Luna）")
    args = ap.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    steps: list[dict] = []
    runtime = LUNA_TRICKCAL / "runtime"

    if not args.skip_contrib:
        steps.append(
            _run(
                [sys.executable, str(HERE / "merge_external_dict.py")],
                cwd=HERE,
            )
        )

    build_cmd = [sys.executable, str(WORK / "overlay_translator" / "build_ko_zh_pairs.py")]
    if args.no_mt:
        build_cmd.append("--no-mt")
    steps.append(_run(build_cmd, cwd=WORK / "overlay_translator"))

    steps.append(
        _run(
            [sys.executable, str(WORK / "luna_integration" / "export_luna_glossary.py")],
            cwd=WORK / "luna_integration",
        )
    )

    if runtime.is_dir() and args.with_patches:
        steps.append(_run([sys.executable, str(LUNA_TRICKCAL / "apply_patches.py")], cwd=LUNA_TRICKCAL))

    apply_cmd = [
        sys.executable,
        str(WORK / "luna_integration" / "apply_luna_trickcal.py"),
        "--luna-root",
        str(runtime),
        "--json-log",
    ]
    steps.append(_run(apply_cmd, cwd=WORK / "luna_integration"))

    ok = all(s.get("ok") for s in steps)
    summary = {
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "success": ok,
        "steps": steps,
    }
    append_log(summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
