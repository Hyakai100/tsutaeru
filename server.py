#!/usr/bin/env python3
"""ツタエル — 看護師長の指示を整えるアシスタント (Python 標準ライブラリのみ)"""
import base64
import hashlib
import hmac
import http.cookies
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlparse

PORT = int(os.environ.get("PORT", "8000"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PASSCODE = os.environ.get("TSUTAERU_PASSCODE", "")
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1000
API_URL = "https://api.anthropic.com/v1/messages"

LINE_CHANNEL_ID = os.environ.get("LINE_CHANNEL_ID", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", f"http://localhost:{PORT}").rstrip("/")
LINE_REDIRECT_URI = f"{APP_BASE_URL}/auth/line/callback"
LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
LINE_PROFILE_URL = "https://api.line.me/v2/profile"
SESSION_COOKIE_NAME = "tsutaeru_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30日
STATE_MAX_AGE = 600  # 10分（CSRF対策stateの有効時間）

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


# ---------- LINEログイン: 署名付きトークン（サーバー側には何も保存しない） ----------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    return hmac.new(AUTH_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(data: dict) -> str:
    """dict を署名付きトークン文字列にする。サーバー側のDB・メモリには何も残さない。"""
    payload = _b64url_encode(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str):
    """署名を検証できれば元の dict を返す。改ざん・不正な場合は None。"""
    if not token or "." not in token:
        return None
    payload, _, sig = token.partition(".")
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        return json.loads(_b64url_decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def make_state() -> str:
    """LINEログイン開始時のCSRF対策state。Cookieもサーバー保存も使わず、署名だけで検証する。"""
    return make_token({"typ": "state", "ts": int(time.time()), "nonce": secrets.token_urlsafe(8)})


def verify_state(state: str) -> bool:
    data = verify_token(state)
    if not data or data.get("typ") != "state":
        return False
    return (int(time.time()) - int(data.get("ts", 0))) <= STATE_MAX_AGE


def make_session_cookie_value(line_user_id: str, display_name: str) -> str:
    exp = int(time.time()) + SESSION_MAX_AGE
    return make_token({"typ": "session", "sub": line_user_id, "name": display_name, "exp": exp})


def verify_session_cookie(value: str):
    data = verify_token(value)
    if not data or data.get("typ") != "session":
        return None
    if int(time.time()) > int(data.get("exp", 0)):
        return None
    return data


# ---------- LINEログイン: LINE側APIの呼び出し ----------

def line_exchange_code(code: str) -> str:
    """認可コードをアクセストークンに交換する。IDトークンは使わないため検証処理は不要。"""
    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LINE_REDIRECT_URI,
        "client_id": LINE_CHANNEL_ID,
        "client_secret": LINE_CHANNEL_SECRET,
    }).encode("utf-8")
    req = urllib.request.Request(
        LINE_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["access_token"]


def line_get_profile(access_token: str) -> dict:
    """profile スコープのアクセストークンでプロフィール（userId・displayName等）を取得する。"""
    req = urllib.request.Request(
        LINE_PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
        path = urlparse(self.path).path
        if path == "/auth/line/login":
            self._handle_line_login()
            return
        if path == "/auth/line/callback":
            self._handle_line_callback()
            return
        if path == "/auth/logout":
            self._handle_logout()
            return
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/check-passcode":
            self._handle_check_passcode()
        elif path == "/api/extract":
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

    def _get_cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
        return jar[name].value if name in jar else ""

    def _current_line_session(self):
        raw = self._get_cookie(SESSION_COOKIE_NAME)
        return verify_session_cookie(raw) if raw else None

    def _is_authorized(self) -> bool:
        """LINEログイン済みセッション、またはパスコード一致のどちらかがあれば許可する。"""
        if self._current_line_session():
            return True
        if not PASSCODE:
            return True
        return self.headers.get("X-Passcode", "").strip() == PASSCODE

    def _handle_check_passcode(self) -> None:
        try:
            session = self._current_line_session()
            if session:
                self._send_json(200, {"ok": True, "required": bool(PASSCODE), "name": session.get("name") or ""})
                return
            body = self._read_json_body()
            provided = (body.get("passcode") or "").strip()
            if not PASSCODE:
                self._send_json(200, {"ok": True, "required": False, "name": None})
                return
            if provided == PASSCODE:
                self._send_json(200, {"ok": True, "required": True, "name": None})
            else:
                self._send_json(401, {"error": "パスコードが正しくありません。"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_extract(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "認証が切れました。ページを再読み込みしてください。"})
            return
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
        if not self._is_authorized():
            self._send_json(401, {"error": "認証が切れました。ページを再読み込みしてください。"})
            return
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

    def _cookie_header(self, value: str, max_age: int) -> str:
        secure = "; Secure" if APP_BASE_URL.startswith("https://") else ""
        return f"{SESSION_COOKIE_NAME}={value}; Path=/; Max-Age={max_age}; HttpOnly{secure}; SameSite=Lax"

    def _redirect(self, location: str, set_cookie: str = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()

    def _handle_line_login(self) -> None:
        if not LINE_CHANNEL_ID:
            self._send_json(500, {"error": "LINE_CHANNEL_ID が設定されていません。"})
            return
        params = {
            "response_type": "code",
            "client_id": LINE_CHANNEL_ID,
            "redirect_uri": LINE_REDIRECT_URI,
            "state": make_state(),
            "scope": "profile",
        }
        self._redirect(f"{LINE_AUTHORIZE_URL}?{urlencode(params)}")

    def _handle_line_callback(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        if query.get("error"):
            self._redirect("/?login_error=1")
            return
        code = (query.get("code") or [None])[0]
        state = (query.get("state") or [None])[0]
        if not code or not state or not verify_state(state):
            self._redirect("/?login_error=1")
            return
        try:
            access_token = line_exchange_code(code)
            profile = line_get_profile(access_token)
            cookie_value = make_session_cookie_value(profile.get("userId", ""), profile.get("displayName", ""))
        except Exception:
            self._redirect("/?login_error=1")
            return
        self._redirect("/", set_cookie=self._cookie_header(cookie_value, SESSION_MAX_AGE))

    def _handle_logout(self) -> None:
        self._redirect("/", set_cookie=self._cookie_header("", 0))


def main() -> None:
    print(f"ツタエル を http://0.0.0.0:{PORT} で起動します")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します")
        server.server_close()


if __name__ == "__main__":
    main()
