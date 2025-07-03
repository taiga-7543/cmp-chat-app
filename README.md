# CMP Chat App

Vertex AI RAGを使用したWebベースのチャットアプリケーションです。

## 機能

- **リアルタイムチャット**: ストリーミングレスポンスによる即座な会話
- **RAG統合**: Vertex AI RAGを使用した高度な質問応答
- **レスポンシブデザイン**: デスクトップ・モバイル対応
- **モダンUI**: 美しいグラデーションとアニメーション

## セットアップ

### 必要要件

- Python 3.8以上
- Google Cloud Project
- Vertex AI APIの有効化
- 適切なRAGコーパスの設定

### インストール

1. リポジトリをクローンします：
```bash
git clone https://github.com/taiga-7543/cmp-chat-app.git
cd cmp-chat-app
```

2. 依存関係をインストールします：
```bash
pip install -r requirements.txt
```

3. 環境変数を設定します：

#### 方法1: 環境変数ファイル (.env)
```bash
# Google Cloud設定
GOOGLE_CLOUD_PROJECT=your-project-id
RAG_CORPUS=projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id
GEMINI_MODEL=gemini-2.5-flash

# Google Cloud認証（どちらか一つを選択）
# 方法A: サービスアカウントキーファイルのパス
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/service-account-key.json

# 方法B: サービスアカウントキーのJSONを直接設定（Renderなどのクラウドサービス向け）
GOOGLE_APPLICATION_CREDENTIALS_JSON={"type": "service_account", "project_id": "your-project-id", ...}
```

#### 方法2: 環境変数を直接設定
```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export RAG_CORPUS="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
export GEMINI_MODEL="gemini-2.5-flash"
export GOOGLE_APPLICATION_CREDENTIALS="path/to/your/service-account-key.json"
```

#### 方法3: Google Cloud SDK認証（ローカル開発用）
```bash
gcloud auth application-default login
```

## 使用方法

### ローカルでの実行

```bash
python app.py
```

アプリケーションは `http://localhost:8080` で起動します。

### 本番環境での実行

```bash
gunicorn --bind 0.0.0.0:8080 app:app
```

## デプロイ

### Render

1. **GitHubリポジトリをRenderに接続**
   - [Render](https://render.com)にログイン
   - 「New +」→「Web Service」を選択
   - GitHubリポジトリを選択

2. **デプロイ設定**
   - **Name**: `cmp-chat-app`（任意の名前）
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT app:app`

3. **環境変数を設定**
   - Renderのダッシュボードで「Environment」タブを選択
   - 以下の環境変数を追加：
     ```
     GOOGLE_CLOUD_PROJECT=your-project-id
     RAG_CORPUS=projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id
     GEMINI_MODEL=gemini-2.5-flash
     GOOGLE_APPLICATION_CREDENTIALS_JSON={"type": "service_account", "project_id": "your-project-id", ...}
     ```

4. **デプロイ実行**
   - 「Create Web Service」をクリック
   - 自動的にビルドとデプロイが開始されます

### Google Cloud Run

1. プロジェクトをビルドしてデプロイ：
```bash
gcloud run deploy cmp-chat-app \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=your-project-id,RAG_CORPUS=projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id,GEMINI_MODEL=gemini-2.5-flash
```

### Heroku

1. `Procfile`を作成：
```
web: gunicorn --bind 0.0.0.0:$PORT app:app
```

2. 環境変数を設定：
```bash
heroku config:set GOOGLE_CLOUD_PROJECT=your-project-id
heroku config:set RAG_CORPUS=projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id
heroku config:set GEMINI_MODEL=gemini-2.5-flash
heroku config:set GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type": "service_account", "project_id": "your-project-id", ...}'
```

3. デプロイ：
```bash
heroku create your-app-name
git push heroku main
```

## ファイル構造

```
cmp-chat-app/
├── app.py              # メインアプリケーション
├── requirements.txt    # 依存関係
├── render.yaml         # Render設定ファイル
├── .env.example        # 環境変数の例
├── .gitignore         # Git除外ファイル
├── templates/
│   └── index.html     # HTMLテンプレート
├── static/
│   └── style.css      # CSSスタイル
└── README.md          # このファイル
```

## 環境変数

| 変数名 | 説明 | デフォルト値 |
|--------|------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Google CloudプロジェクトID | `dotd-development-division` |
| `RAG_CORPUS` | RAGコーパスの完全なリソース名 | `projects/{PROJECT_ID}/locations/us-central1/ragCorpora/3458764513820540928` |
| `GEMINI_MODEL` | 使用するGeminiモデル | `gemini-2.5-flash` |
| `GOOGLE_APPLICATION_CREDENTIALS` | サービスアカウントキーファイルのパス | - |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | サービスアカウントキーのJSON文字列 | - |

## カスタマイズ

### RAGコーパスの変更

環境変数`RAG_CORPUS`を変更して、異なるRAGコーパスを使用できます：

```bash
export RAG_CORPUS="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
```

### UIの変更

- `templates/index.html`: HTML構造
- `static/style.css`: スタイルとレイアウト

### モデルの変更

環境変数`GEMINI_MODEL`を変更して、異なるGeminiモデルを使用できます：

```bash
export GEMINI_MODEL="gemini-2.0-flash-exp"
```

## トラブルシューティング

### 認証エラー

- Google Cloud認証情報が正しく設定されているか確認
- プロジェクトIDが正しいか確認
- Vertex AI APIが有効化されているか確認

### RAGコーパスエラー

- コーパスIDが正しいか確認
- コーパスが存在し、アクセス可能か確認
- リージョンが一致しているか確認

### Renderデプロイエラー

- 環境変数が正しく設定されているか確認
- サービスアカウントキーのJSONが正しい形式か確認
- ビルドログでエラーの詳細を確認

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。 