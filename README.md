# ツタエル (Tsutaeru)

看護師長が部下に伝える「雑な指示」を、AI が **明確で・相手が萎縮しない言葉** に整えるシンプルな Web アプリです。

## 使い方（3ステップ）

1. **雑な指示を入力する**（例：「田中さん、ちゃんと見ておいて」）
2. AI が **5要素** に整理 → 師長が編集して **「この内容で確定」**
   - ① ターゲット（誰に） ② 観察点・内容 ③ 期限 ④ 重要度★1〜3 ⑤ 次につながること
3. AI が部下向けに **「温かい版」「端的版」** の2つのメッセージを提案。それぞれ「コピー」または **「LINEで送る」** で、そのままLINEの友だち・トーク選択画面を開いて送れます

## 構成

- `server.py` … Python 標準ライブラリ (`http.server` + `urllib`) だけで動くサーバー
- `index.html` … LINE WORKS風のビジネスチャットUI（スマホ最優先・デスクトップ対応）
- `requirements.txt` … 外部依存なし（空）
- `render.yaml` … Render 用のデプロイ設定

外部フレームワーク・データベース・課金は **一切使いません**。認証はLINEログイン／パスコードの併存、LINEへの送信はLINE公式のLIFF SDK（`index.html` から読み込む1本のスクリプトタグのみ。ビルド時の依存関係はなし）を使用します。

## 必要なもの

- Python 3.10 以上
- Anthropic の API キー（環境変数 `ANTHROPIC_API_KEY`）
- （任意）共有パスコード（環境変数 `TSUTAERU_PASSCODE`）
- （任意）LINEログイン用のチャネル情報（環境変数 `LINE_CHANNEL_ID` / `LINE_CHANNEL_SECRET` / `AUTH_SECRET`）
- （任意）LINEで送る機能用のLIFF ID（環境変数 `LIFF_ID`）

## ログイン方法（LINEログイン＋パスコードの併存）

ゲート画面では「LINEでログイン」ボタンが主導線、その下の「パスコードをお持ちの方はこちら」から
従来のパスコード入力に切り替えられます。どちらか一方が通れば利用できます。

### LINEログイン

- LINE Login（OAuth 2.0 / v2.1）を使用。取得するのは `profile` スコープのみ（ユーザーID・表示名・アイコンURL）
- ログイン状態は署名付きCookie（HMAC-SHA256）で保持。**サーバー側には何も保存しません**（データベース・ファイル不使用）
- 有効期限は30日。ログアウトはCookie削除のみで、サーバー側の強制失効機能はありません
- 必要な環境変数：
  - `LINE_CHANNEL_ID` / `LINE_CHANNEL_SECRET` … [LINE Developers](https://developers.line.biz/) でLINEログインチャネルを作成して取得
  - `AUTH_SECRET` … セッション・CSRF対策の署名用。`python -c "import secrets; print(secrets.token_hex(32))"` などで自分で生成し、Renderの環境変数に設定
  - `APP_BASE_URL` … 公開URL（例：`https://tsutaeru.onrender.com`）。LINE Developersのコールバック設定と完全に一致させること（コールバックURLは `{APP_BASE_URL}/auth/line/callback`）
- 未設定（`LINE_CHANNEL_ID` が空）の場合、LINEログインは使えずパスコードのみで運用できます

### LINEで送る機能（LIFF）

確定したメッセージ（温かい版・端的版）の「LINEで送る」ボタンから、LINEの友だち・トーク選択画面（shareTargetPicker）を開いて、そのまま送信できます。

- LINE公式のLIFF（LINE Front-end Framework）を使用。コピー＆ペースト不要でLINEに送れます
- 送信は**師長自身のLINEアカウントから、選んだ友だち・トークへの発信**として行われます。部下側は「ツタエルを友だち追加する」等の準備は一切不要です
- 必要な環境変数：
  - `LIFF_ID` … [LINE Developers](https://developers.line.biz/) で、既存のLINEログインチャネルに新規LIFFアプリを追加して取得。**Share Target Picker機能を有効にすること**、Endpoint URLは公開URL（例：`https://tsutaeru.onrender.com`）を設定
  - シークレットではないため、コード上で扱っても問題ない値ですが、他の設定と同様にRenderの環境変数から読み込みます
- 未設定（`LIFF_ID` が空）の場合、「LINEで送る」ボタンを押すと案内メッセージが表示され、「コピー」機能のみで運用できます
- 外部ブラウザ（LINEアプリの外）から使う場合、初回だけLINE側の許可画面に一度切り替わることがあります（2回目以降は不要）

### パスコード認証（併存・任意）

`TSUTAERU_PASSCODE` を設定すると、ゲート画面のパスコード欄が機能します。

- 未設定なら誰でも使えます（従来通り）
- LINEログインするほどではない相手（面談・デモ等）に見せる用途を想定
- 認証後は同じタブ内ではセッションが続き、タブを閉じると再入力が必要です
- 期間終了時は Render のダッシュボードで `TSUTAERU_PASSCODE` を削除するか、サービスを Suspend/Archive してください

## ローカルで起動する

**Windows (PowerShell)**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python server.py
```

**macOS / Linux**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python server.py
```

ブラウザで <http://localhost:8000> を開いてください。
ポートは `PORT` 環境変数で変更できます。

## Render にデプロイする

1. このフォルダを GitHub リポジトリにプッシュします。
2. [Render Dashboard](https://dashboard.render.com/) で **New +** → **Blueprint** を選択。
3. GitHub リポジトリを接続すると `render.yaml` が自動で読み込まれます。
4. デプロイ設定の **Environment** タブで以下を設定します（すべて Render のダッシュボード上でのみ設定し、コードやコミットには絶対に書かないでください）。
   - `ANTHROPIC_API_KEY`
   - （任意）`TSUTAERU_PASSCODE`
   - （任意・LINEログインを使う場合）`LINE_CHANNEL_ID` / `LINE_CHANNEL_SECRET` / `AUTH_SECRET` / `APP_BASE_URL`（例：`https://tsutaeru.onrender.com`）
   - （任意・LINEで送る機能を使う場合）`LIFF_ID`
5. **Apply** を押すと数分でビルドが完了し、`https://<サービス名>.onrender.com` で開けます。
6. LINEログインを使う場合は、[LINE Developers](https://developers.line.biz/) のチャネル設定で、コールバックURLに `https://<サービス名>.onrender.com/auth/line/callback` を登録してください。
7. LINEで送る機能を使う場合は、同じチャネルにLIFFアプリを追加し、Endpoint URLに `https://<サービス名>.onrender.com` を、Share Target Picker機能を有効にして登録してください。

## モデル・API 仕様

- モデル: `claude-haiku-4-5`（試作向けにコスト抑制。より賢い `claude-sonnet-4-5-20250929` などに変更可）
- `max_tokens`: 1000
- `anthropic-version`: `2023-06-01`
- エンドポイント: `POST /api/check-passcode`, `POST /api/extract`, `POST /api/message`, `GET /api/config`, `GET /auth/line/login`, `GET /auth/line/callback`, `GET /auth/logout`

## セキュリティのお願い

- API キーは **必ず環境変数** から読み込みます。コード・README・コミットには絶対に書かないでください。
- 公開リポジトリでも動く前提で作っていますが、Render の無料プランでは一定時間アクセスがないとスリープするため、初回アクセスに少し時間がかかる場合があります。
