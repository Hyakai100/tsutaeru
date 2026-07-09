# つたえる (Tsutaeru)

看護師長が部下に伝える「雑な指示」を、AI が **明確で・相手が萎縮しない言葉** に整えるシンプルな Web アプリです。

## 使い方（3ステップ）

1. **雑な指示を入力する**（例：「田中さん、ちゃんと見ておいて」）
2. AI が **5要素** に整理 → 師長が編集して **「この内容で確定」**
   - ① ターゲット（誰に） ② 観察点・内容 ③ 期限 ④ 重要度★1〜3 ⑤ 次につながること
3. AI が部下向けに **「温かい版」「端的版」** の2つのメッセージを提案

## 構成

- `server.py` … Python 標準ライブラリ (`http.server` + `urllib`) だけで動くサーバー
- `index.html` … 3ステップの UI（スマホ対応・落ち着いた配色）
- `requirements.txt` … 外部依存なし（空）
- `render.yaml` … Render 用のデプロイ設定

外部フレームワーク・データベース・ログイン・課金は **一切使いません**。

## 必要なもの

- Python 3.10 以上
- Anthropic の API キー（環境変数 `ANTHROPIC_API_KEY`）

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
4. デプロイ設定の **Environment** タブで `ANTHROPIC_API_KEY` にキーを貼り付けます。
   ⚠️ **キーはコードやコミットに入れないでください。**Render のダッシュボード上でのみ設定します。
5. **Apply** を押すと数分でビルドが完了し、`https://<サービス名>.onrender.com` で開けます。

## モデル・API 仕様

- モデル: `claude-sonnet-4-5-20250929`
- `max_tokens`: 1000
- `anthropic-version`: `2023-06-01`
- エンドポイント: `POST /api/extract`, `POST /api/message`

## セキュリティのお願い

- API キーは **必ず環境変数** から読み込みます。コード・README・コミットには絶対に書かないでください。
- 公開リポジトリでも動く前提で作っていますが、Render の無料プランでは一定時間アクセスがないとスリープするため、初回アクセスに少し時間がかかる場合があります。
