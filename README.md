# Vertex AI RAG

Google Drive同期機能を持つRAG（Retrieval-Augmented Generation）アプリケーション

## 📁 プロジェクト構造

```
vertex-ai-rag/
├── app.py                          # メインアプリケーション
├── drive_sync_integration.py       # Google Drive同期機能
├── requirements.txt                # Python依存関係
├── .env                           # 環境変数（本番用）
├── config/                        # 設定ファイル
│   ├── client_secrets.json.template # OAuth設定テンプレート
│   ├── client_secrets.json        # OAuth設定（機密）
│   ├── .env.example               # 環境変数例
│   └── rag-service-account-key.json # サービスアカウントキー（機密）
├── deployment/                    # デプロイメント設定
│   ├── vercel.json               # Vercel設定
│   ├── railway.json              # Railway設定
│   ├── render.yaml               # Render設定
│   ├── Dockerfile                # Docker設定
│   ├── .dockerignore             # Docker除外ファイル
│   └── cloud_functions_deploy.yaml # Cloud Functions設定
├── docs/                         # ドキュメント
│   ├── DEPLOYMENT.md             # デプロイメントガイド
│   └── setup_oauth.md            # OAuth設定ガイド
├── scripts/                      # スクリプト・ユーティリティ
│   ├── setup-env.sh              # 環境セットアップ
│   ├── drive_webhook_setup.py    # Webhookセットアップ
│   └── user_auth_example.py      # 認証例
├── temp/                         # 一時ファイル・ログ
│   ├── drive_sync_state.json     # 同期状態
│   └── google_drive_token.pickle # 認証トークン
├── templates/                    # HTMLテンプレート
├── static/                       # 静的ファイル（CSS, JS）
└── uploads/                      # アップロード用ディレクトリ
```

## 🚀 クイックスタート

### 1. 環境設定

```bash
# 依存関係をインストール
pip install -r requirements.txt

# 環境変数を設定
cp config/.env.example .env
# .envファイルを編集
```

### 2. Google Cloud設定

```bash
# OAuth設定
cp config/client_secrets.json.template config/client_secrets.json
# client_secrets.jsonを編集
```

### 3. アプリケーション起動

```bash
python app.py
```

ブラウザで `http://localhost:8080` にアクセス

**認証情報:**
- ユーザー名: `admin`
- パスワード: `password123`

## ✨ 主な機能

- **RAG（Retrieval-Augmented Generation）**: ドキュメントベースの質問応答
- **Google Drive同期**: ドキュメントの自動同期
- **共有ドライブ対応**: 企業用共有ドライブサポート
- **ドキュメント管理**: アップロード・削除・一覧表示
- **リアルタイムチャット**: ストリーミング応答
- **認証システム**: 基本認証によるアクセス制御

## 📚 ドキュメント

- [デプロイメントガイド](docs/DEPLOYMENT.md)
- [OAuth設定ガイド](docs/setup_oauth.md)

## 🔧 開発

### ディレクトリ構造の意図

- `config/`: 機密性の高い設定ファイルを分離
- `deployment/`: プラットフォーム別デプロイメント設定を整理
- `docs/`: ドキュメントを集約
- `scripts/`: ユーティリティスクリプトを整理
- `temp/`: 一時ファイル・ログを分離（.gitignoreで除外）

### 環境変数

主要な環境変数は `.env` ファイルで管理されています。詳細は `config/.env.example` を参照してください。

### 認証設定

Google Cloud認証は以下のファイルで設定：
- `config/client_secrets.json`: OAuth設定
- `config/rag-service-account-key.json`: サービスアカウント設定

## 📄 ライセンス

このプロジェクトはMITライセンスの下で公開されています。詳細は [LICENSE](LICENSE) ファイルを参照してください。 