#!/usr/bin/env python3
"""つたえる — 看護師長の指示を整えるアシスタント (Python 標準ライブラリのみ)"""
import http.server
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", "8000"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1000
API_URL = "https://api.anthropic.com/v1/messages"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def call_claude(system_prompt: str, user_message: str) -> str:
    """Anthropic Messages API を urllib で直接呼び、テキスト本文を返す。"""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が設定されていません。環境変数にキーを入れて再起動してください。"
        )
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Claude API エラー ({e.code}): {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Claude API に接続できませんでした: {e.reason}") from e

    for part in data.get("content", []):
        if part.get("type") == "text":
            return part.get("text", "")
    return ""


def extract_json(text: str):
    """応答テキストから最初の { と最後の } の間を取り出して JSON としてパースする。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("AI の応答から JSON を取り出せませんでした。")
    return json.loads(text[start : end + 1])


EXTRACT_SYSTEM_PROMPT = """あなたは看護管理を支える丁寧なアシスタントです。
師長さんが部下に伝えたい指示文を、次の5要素に整理してください。
不足している要素は、状況から自然に推測できる範囲で仮の内容を入れてください（師長さんが後から編集します）。
重要度は現場感覚から仮に★1〜★3の整数で提案してください。

  ★1 = 通常業務の一環
  ★2 = 注意して観察してほしい
  ★3 = 見逃せない/急ぎ

必ず以下の JSON 形式だけを返してください。前後に説明文を入れないでください。

{
  "target": "誰に対する指示か（例：田中看護師、夜勤スタッフ全員 など）",
  "content": "観察点や依頼したい具体的な内容",
  "deadline": "いつまでに / どのタイミングで / どの頻度で など",
  "importance": 1〜3のいずれかの整数,
  "next_step": "報告先や次のアクション"
}"""


MESSAGE_SYSTEM_PROMPT = """あなたは看護現場の師長さんの言葉を、部下が萎縮せずに理解できる伝え方に整えるアシスタントです。
5要素の指示情報（JSON）を受け取り、部下に送るためのメッセージを日本語で2種類作成してください。

  - warm: 温かく相手を尊重しながら、期限・重要度・次のアクションが伝わる丁寧な伝え方
  - concise: 忙しい現場向けに要点だけを短くまとめた、テキパキした伝え方

どちらも威圧的・命令口調にならないようにしてください。長すぎず、読みやすい長さにまとめてください。
必ず以下の JSON 形式だけを返してください。前後に説明文を入れないでください。

{
  "warm": "温かい版のメッセージ本文",
  "concise": "端的版のメッセージ本文"
}"""


def normalize_five(d: dict) -> dict:
    """5要素の型・範囲を安全に揃える。"""
    try:
        imp = int(d.get("importance", 2))
    except (ValueError, TypeError):
        imp = 2
    imp = max(1, min(3, imp))
    return {
        "target": str(d.get("target") or "").strip(),
        "content": str(d.get("content") or "").strip(),
        "deadline": str(d.get("deadline") or "").strip(),
        "importance": imp,
        "next_step": str(d.get("next_step") or "").strip(),
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/extract":
            self._handle_extract()
        elif path == "/api/message":
            self._handle_message()
        else:
            self.send_error(404, "Not Found")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, obj: dict) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_extract(self) -> None:
        try:
            body = self._read_json_body()
            instruction = (body.get("instruction") or "").strip()
            if not instruction:
                self._send_json(400, {"error": "指示文が入力されていません。"})
                return
            reply = call_claude(EXTRACT_SYSTEM_PROMPT, instruction)
            data = normalize_five(extract_json(reply))
            self._send_json(200, data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_message(self) -> None:
        try:
            body = self._read_json_body()
            summary = normalize_five(body)
            reply = call_claude(
                MESSAGE_SYSTEM_PROMPT,
                json.dumps(summary, ensure_ascii=False),
            )
            data = extract_json(reply)
            warm = data.get("warm", "")
            concise = data.get("concise", "")
            self._send_json(
                200,
                {
                    "warm": warm if isinstance(warm, str) else "",
                    "concise": concise if isinstance(concise, str) else "",
                },
            )
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def main() -> None:
    print(f"つたえる を http://0.0.0.0:{PORT} で起動します")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します")
        server.server_close()


if __name__ == "__main__":
    main()
