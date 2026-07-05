import zipfile
import re
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

apk = r"d:\ch\opaivmplayer\localization_work\com.epidgames.trickcalrevive.base.apk"
z = zipfile.ZipFile(apk)
names = z.namelist()

print("=== All assets/ files ===")
for n in sorted(names):
    if n.startswith("assets/") and not n.endswith("/"):
        info = z.getinfo(n)
        print(f"{info.file_size:>12}  {n}")

print("\n=== dic/ folder contents preview ===")
for n in sorted(names):
    if n.startswith("assets/dic"):
        data = z.read(n)
        print(f"\n--- {n} ({len(data)} bytes) ---")
        if len(data) < 5000:
            try:
                print(data.decode("utf-8", errors="replace")[:2000])
            except Exception:
                print(repr(data[:200]))
        else:
            print("binary/large, magic:", data[:16].hex())

print("\n=== Keyword search in APK ===")
raw = z.read("classes.dex") if "classes.dex" in names else b""
apk_raw = open(apk, "rb").read()
keywords = [
    b"I2Languages", b"Localization", b"ko-KR", b"Korean", b"SystemLanguage",
    b"TextAsset", b"LanguageManager", b"Locale", b"StringTable", b"libData",
    b"ATG_E", b"Decrypt", b"AssetBundle", b"GetString", b"TableManager",
]
for kw in keywords:
    count = apk_raw.count(kw)
    print(f"  {kw.decode('ascii', errors='replace')}: {count} occurrences")

print("\n=== Korean string extraction (all assets) ===")
korean_re = re.compile(r"[\uAC00-\uD7AF\u3131-\u318E\s\d\.,!?]{4,}")
all_korean = set()
for info in z.infolist():
    if not info.filename.startswith("assets/"):
        continue
    if info.file_size > 100_000_000:
        continue
    data = z.read(info.filename)
    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(enc, errors="ignore")
        except Exception:
            continue
        for m in korean_re.findall(text):
            if len(m.strip()) >= 4 and re.search(r"[\uAC00-\uD7AF]", m):
                all_korean.add(m.strip()[:120])

print(f"Unique Korean-like strings found: {len(all_korean)}")
for s in sorted(all_korean)[:30]:
    print(" ", s)
if len(all_korean) > 30:
    print(f"  ... and {len(all_korean)-30} more")

# Save full list
out = r"d:\ch\opaivmplayer\localization_work\korean_strings_raw.txt"
with open(out, "w", encoding="utf-8") as f:
    for s in sorted(all_korean):
        f.write(s + "\n")
print(f"\nSaved to {out}")
