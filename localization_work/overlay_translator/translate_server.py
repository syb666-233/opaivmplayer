"""轻量本地翻译 API，供 Frida 脚本或外部工具调用。"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from deep_translator import GoogleTranslator

translator = GoogleTranslator(source="ko", target="zh-CN")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
            text = data.get("text", "")
            out = translator.translate(text) if text.strip() else ""
            resp = json.dumps({"text": text, "translated": out}, ensure_ascii=False)
            code = 200
        except Exception as e:
            resp = json.dumps({"error": str(e)}, ensure_ascii=False)
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(resp.encode("utf-8"))

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    host, port = "127.0.0.1", 8787
    print(f"Translation API on http://{host}:{port}/translate")
    HTTPServer((host, port), Handler).serve_forever()
