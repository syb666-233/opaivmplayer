"""
一键应用 Trickcal 优化 1/2/3/6 到 LunaTrickcal/runtime。

用法（在 LunaTrickcal 目录）:
  py -3 apply_trickcal_optimizations.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
RUNTIME = HERE / "runtime"
LOG = HERE / "logs" / "optimization_apply.json"


def main() -> int:
    steps = []
    started = datetime.now(timezone.utc).isoformat()

    r = subprocess.run([sys.executable, str(HERE / "apply_patches.py")], cwd=str(HERE))
    steps.append({"step": "apply_patches", "exit_code": r.returncode})

    r = subprocess.run(
        [sys.executable, str(HERE / "scripts" / "sync_trickcal_dict.py")],
        cwd=str(HERE),
    )
    steps.append({"step": "sync_trickcal_dict", "exit_code": r.returncode})

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        json.dumps(
            {"started": started, "finished": datetime.now(timezone.utc).isoformat(), "steps": steps},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if all(s["exit_code"] == 0 for s in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
