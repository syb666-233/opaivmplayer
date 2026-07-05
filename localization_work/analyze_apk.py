import zipfile
import re
import os

apk = r"d:\ch\opaivmplayer\localization_work\com.epidgames.trickcalrevive.base.apk"
z = zipfile.ZipFile(apk)
names = z.namelist()
print("Total entries:", len(names))

assets = [n for n in names if n.startswith("assets/")]
libs = [n for n in names if n.startswith("lib/")]
res = [n for n in names if n.startswith("res/")]
print("assets:", len(assets), "lib:", len(libs), "res:", len(res))

patterns = ["local", "lang", "i2", "string", "text", "table", "bundle", "unity"]
for p in patterns:
    matched = [n for n in assets if p.lower() in n.lower()]
    if matched:
        print(f"\n=== assets matching '{p}' ({len(matched)}) ===")
        for m in matched[:25]:
            print(" ", m)
        if len(matched) > 25:
            print("  ...")

folders = set()
for n in assets:
    parts = n.split("/")
    if len(parts) >= 2:
        folders.add(parts[1])
print("\nAsset subfolders:", sorted(folders))

# Scan raw bytes for Korean Hangul strings
print("\n=== Scanning for Korean text in assets ===")
korean_re = re.compile(r"[\uAC00-\uD7AF]{2,}")
korean_samples = []
for info in z.infolist():
    if not info.filename.startswith("assets/"):
        continue
    if info.file_size > 50_000_000:
        continue
    data = z.read(info.filename)
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        continue
    matches = korean_re.findall(text)
    if matches:
        korean_samples.append((info.filename, info.file_size, matches[:5]))

korean_samples.sort(key=lambda x: -x[1])
print(f"Files with Korean text (utf-8 scan): {len(korean_samples)}")
for fn, size, samples in korean_samples[:15]:
    print(f"  {fn} ({size} bytes): {samples}")

# Scan entire APK for localization keywords
raw = open(apk, "rb").read()
for kw in [b"I2Languages", b"Localization", b"ko-KR", b"Korean", b"SystemLanguage", b"TextAsset"]:
    idx = raw.find(kw)
    print(f"\nKeyword {kw!r}: {'found at ' + str(idx) if idx >= 0 else 'NOT found'}")
