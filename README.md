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
git clone <repository-url>
cd vertex-ai-rag
```

2. 依存関係をインストールします：
```bash
pip install -r requirements.txt
```

3. 環境変数を設定します：
```bash
# Google Cloud認証情報を設定
export GOOGLE_APPLICATION_CREDENTIALS="path/to/your/service-account-key.json"
```

または、Google Cloud SDK認証を使用：
```bash
gcloud auth application-default login
```

### 設定

`app.py`内の以下の設定を環境に合わせて変更してください：

```python
# プロジェクトID
project="your-project-id"

# RAGコーパスID
rag_corpus="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
```

## 使用方法

### ローカルでの実行

```bash
python app.py
```

アプリケーションは `http://localhost:5000` で起動します。

### 本番環境での実行

```bash
gunicorn --bind 0.0.0.0:8080 app:app
```

## デプロイ

### Google Cloud Run

1. プロジェクトをビルドしてデプロイ：
```bash
gcloud run deploy rag-chat-app \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### Heroku

1. `Procfile`を作成：
```
web: gunicorn app:app
```

2. デプロイ：
```bash
heroku create your-app-name
git push heroku main
```

### その他のプラットフォーム

このアプリケーションは標準的なFlaskアプリケーションなので、Railway、Render、Vercelなどの様々なプラットフォームにデプロイできます。

## ファイル構造

```
vertex-ai-rag/
├── app.py              # メインアプリケーション
├── requirements.txt    # 依存関係
├── templates/
│   └── index.html     # HTMLテンプレート
├── static/
│   └── style.css      # CSSスタイル
└── README.md          # このファイル
```

## カスタマイズ

### RAGコーパスの変更

`app.py`内の`rag_corpus`変数を変更して、異なるRAGコーパスを使用できます。

### UIの変更

- `templates/index.html`: HTML構造
- `static/style.css`: スタイルとレイアウト

### モデルの変更

`app.py`内の`model`変数を変更して、異なるGeminiモデルを使用できます：

```python
model = "gemini-2.5-pro"  # または他のモデル
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

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。 