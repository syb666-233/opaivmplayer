import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"d:\ch\opaivmplayer\localization_work\extracted")

KEYWORDS = [
    b"dic", b"libData", b"Decrypt", b"Encrypt", b"Local", b"Locale", b"Language",
    b"String", b"Text", b"Table", b"Bundle", b"Asset", b"ATG", b"Load", b"GetString",
    b"UnityEngine.UI.Text", b"TMP_Text", b"TextMeshPro", b"I2", b"Translation",
    b"ko", b"KR", b"UTF", b"json", b"csv", b"xlsx",
]


def scan_binary(path: Path, limit_ctx=80):
    data = path.read_bytes()
    print(f"\n{'='*60}\n{path.name} ({len(data)} bytes)\n{'='*60}")
    for kw in KEYWORDS:
        idx = 0
        hits = 0
        while hits < 8:
            idx = data.find(kw, idx)
            if idx == -1:
                break
            ctx = data[max(0, idx - 30): idx + len(kw) + 50]
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in ctx)
            print(f"  [{kw.decode('ascii', errors='replace')}] @{idx}: {printable}")
            idx += 1
            hits += 1
        if hits == 8:
            print(f"  ... more hits for {kw!r}")


def analyze_dic(path: Path):
    data = path.read_bytes()
    print(f"\n--- dic file analysis ({len(data)} bytes) ---")
    print("Header hex:", data[:64].hex())
    print("Entropy estimate:", len(set(data)) / 256)
    # look for repeating 4-byte patterns
    from collections import Counter
    chunks = Counter(data[i:i+4] for i in range(0, len(data)-4, 4))
    print("Most common 4-byte chunks:", chunks.most_common(5))


def scan_metadata(path: Path):
    data = path.read_bytes().decode("utf-8", errors="ignore")
    patterns = [
        r"Local\w+", r"Lang\w+", r"String\w+", r"Text\w+", r"Table\w+",
        r"I2\w*", r"Locale\w+", r"Dic\w+", r"ATG\w+", r"Decrypt\w+", r"Encrypt\w+",
        r"Trickcal\w*", r"Epid\w*", r"TableManager", r"DataManager",
    ]
    found = set()
    for pat in patterns:
        for m in re.finditer(pat, data):
            s = m.group()
            if 3 <= len(s) <= 80:
                found.add(s)
    print(f"\n--- global-metadata interesting symbols ({len(found)}) ---")
    for s in sorted(found):
        if any(k in s.lower() for k in ["local", "lang", "string", "text", "table", "dic", "atg", "decrypt", "locale", "i2"]):
            print(" ", s)


if __name__ == "__main__":
    analyze_dic(ROOT / "assets_dic")
    for name in ["assets_libData.so", "libATG_D.so", "libATG_L.so", "libmain.so"]:
        p = ROOT / name
        if p.exists():
            scan_binary(p)
    scan_metadata(ROOT / "assets_bin_Data_Managed_Metadata_global-metadata.dat")
