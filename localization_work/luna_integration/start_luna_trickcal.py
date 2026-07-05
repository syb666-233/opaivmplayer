"""Launch LunaTranslator.exe (avoids batch encoding issues)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = (
    ROOT / "LunaTranslator_x64" / "LunaTranslator.exe",
    ROOT / "LunaTranslator" / "LunaTranslator_x64_win10" / "LunaTranslator.exe",
)


def main() -> int:
    for exe in CANDIDATES:
        if exe.is_file():
            print(f"Starting: {exe}")
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            return 0
    print("LunaTranslator.exe not found.")
    print("Extract LunaTranslator_x64_win10.zip into localization_work\\")
    return 1


if __name__ == "__main__":
    sys.exit(main())
