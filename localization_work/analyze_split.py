import zipfile
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

split_apk = r"d:\ch\opaivmplayer\localization_work\config.arm64_v8a.apk"
z = zipfile.ZipFile(split_apk)
names = z.namelist()
print("Entries:", len(names))
for n in sorted(names):
    if not n.endswith("/"):
        print(f"{z.getinfo(n).file_size:>12}  {n}")

raw = open(split_apk, "rb").read()
korean_re = re.compile(r"[\uAC00-\uD7AF]{3,}")
# find readable korean sentences in raw file
sentences = set()
for m in re.finditer(r"[\uAC00-\uD7AF][\uAC00-\uD7AF\s\d\.,!?·…「」『』（）:]{4,120}", raw.decode("utf-8", errors="ignore")):
    s = m.group().strip()
    if sum(1 for c in s if "\uAC00" <= c <= "\uD7AF") >= 4:
        sentences.add(s)

print(f"\nReadable Korean sentences in split APK: {len(sentences)}")
for s in sorted(sentences)[:30]:
    print(" ", s)

for kw in [b".bundle", b"AssetBundle", b"localization", b"string", b".bytes", b"table"]:
    c = raw.count(kw)
    print(f"{kw}: {c}")
