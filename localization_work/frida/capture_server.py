"""
Frida 韩文抓取 + 配对服务。

端点:
  POST /capture   {"text":"...", "source":"..."}  → 写入 ko_captured.jsonl
  POST /translate {"text":"..."}                → 翻译（供调试）
  POST /build_pairs                             → 从抓取记录生成 ko_zh_pairs.json
  GET  /stats

用法:
  py -3 capture_server.py
  adb forward tcp:8787 tcp:8787
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_LOG = ROOT / "frida" / "ko_captured.jsonl"
PAIRS_PATH = ROOT / "overlay_translator" / "ko_zh_pairs.json"

sys.path.insert(0, str(ROOT / "overlay_translator"))

_lock = threading.Lock()
_stats = {"captured": 0, "unique": 0, "pairs": 0}
_unique: set[str] = set()


def _load_unique() -> None:
    global _unique
    if not CAPTURE_LOG.is_file():
        return
    for line in CAPTURE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            t = (row.get("text") or "").strip()
            if t:
                _unique.add(t)
        except json.JSONDecodeError:
            continue
    _stats["unique"] = len(_unique)


def _append_capture(text: str, source: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "source": source or "frida",
    }
    with _lock:
        is_new = text not in _unique
        CAPTURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CAPTURE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if is_new:
            _unique.add(text)
            _stats["unique"] = len(_unique)
        _stats["captured"] += 1
    return is_new


def _build_pairs() -> dict:
    from build_ko_zh_pairs import build_pairs

    result = build_pairs(
        capture_path=CAPTURE_LOG,
        out_path=PAIRS_PATH,
    )
    _stats["pairs"] = result.get("count", 0)
    return result


class Handler(BaseHTTPRequestHandler):
    def _json_response(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/stats":
            self._json_response(200, {"ok": True, "stats": _stats})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid json"})
            return

        if path == "/capture":
            text = data.get("text", "")
            source = data.get("source", "frida")
            is_new = _append_capture(text, source)
            print(f"[capture] {'NEW' if is_new else 'dup'} {text[:80]}", flush=True)
            self._json_response(200, {"ok": True, "new": is_new, "unique": _stats["unique"]})
            return

        if path == "/translate":
            from translator_backends import translate_game_text

            text = data.get("text", "")
            out = translate_game_text(text, dialog=len(text) > 30)
            self._json_response(200, {"text": text, "translated": out})
            return

        if path == "/build_pairs":
            try:
                result = _build_pairs()
                self._json_response(200, {"ok": True, **result})
            except Exception as exc:
                self._json_response(500, {"error": str(exc)})
            return

        self._json_response(404, {"error": "not found"})

    def log_message(self, fmt, *args) -> None:
        return


def main() -> None:
    _load_unique()
    host, port = "0.0.0.0", 8787
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Capture server http://127.0.0.1:{port}", flush=True)
    print(f"  POST /capture  → {CAPTURE_LOG.name}", flush=True)
    print(f"  POST /build_pairs → {PAIRS_PATH.name}", flush=True)
    print(f"  unique loaded: {_stats['unique']}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
