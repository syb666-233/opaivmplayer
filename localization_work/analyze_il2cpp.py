import zipfile
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

apk = r"d:\ch\opaivmplayer\localization_work\com.epidgames.trickcalrevive.base.apk"
z = zipfile.ZipFile(apk)

# Read meaningful Korean from global-metadata.dat (Il2Cpp)
meta = z.read("assets/bin/Data/Managed/Metadata/global-metadata.dat")
text = meta.decode("utf-8", errors="ignore")
korean_re = re.compile(r"[\uAC00-\uD7AF][\uAC00-\uD7AF\s\d\.,!?·…「」『』（）\(\)\[\]：:；;]{2,80}")
strings = set()
for m in korean_re.findall(text):
    s = m.strip()
    if len(s) >= 3 and sum(1 for c in s if "\uAC00" <= c <= "\uD7AF") >= 2:
        strings.add(s)

print(f"Korean strings in global-metadata.dat: {len(strings)}")
for s in sorted(strings)[:50]:
    print(" ", s)

# Check classes.dex for localization class names
dex = z.read("classes.dex")
for pat in [b"Localization", b"Language", b"StringTable", b"TableData", b"TextData", b"Locale", b"dic", b"libData", b"Decrypt"]:
    idx = 0
    hits = []
    while True:
        idx = dex.find(pat, idx)
        if idx == -1:
            break
        ctx = dex[max(0, idx-20):idx+len(pat)+40]
        hits.append(ctx)
        idx += 1
    if hits:
        print(f"\n=== dex hits for {pat.decode()} ({len(hits)}) ===")
        for h in hits[:5]:
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in h)
            print(" ", printable)

# Analyze libData.so strings
lib = z.read("assets/libData.so")
lib_text = lib.decode("utf-8", errors="ignore")
lib_korean = korean_re.findall(lib_text)
print(f"\nKorean in libData.so: {len(set(lib_korean))}")
for s in sorted(set(lib_korean))[:20]:
    print(" ", s)

# Count readable Korean from korean_strings_raw with quality filter
raw_path = r"d:\ch\opaivmplayer\localization_work\korean_strings_raw.txt"
quality = []
with open(raw_path, encoding="utf-8") as f:
    for line in f:
        s = line.strip()
        hangul = sum(1 for c in s if "\uAC00" <= c <= "\uD7AF")
        if hangul >= max(3, len(s) * 0.5) and len(s) <= 100:
            quality.append(s)
print(f"\nHigh-quality Korean strings (filtered): {len(quality)}")
for s in quality[:40]:
    print(" ", s)

with open(r"d:\ch\opaivmplayer\localization_work\korean_strings_quality.txt", "w", encoding="utf-8") as f:
    for s in sorted(set(quality)):
        f.write(s + "\n")
