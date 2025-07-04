# Vertex AI RAG アプリケーション

Google Cloud Vertex AIを使用したRAG（Retrieval-Augmented Generation）アプリケーションです。

## 機能

- **RAG機能**: Vertex AIのRAGコーパスを使用した情報検索・回答生成
- **深掘りモード**: 包括的な調査と関連質問の自動生成
- **基本認証**: セキュアなアクセス制御
- **リアルタイムストリーミング**: Server-Sent Eventsを使用したリアルタイム回答
- **出典情報**: 回答の根拠となるドキュメントの表示

## デプロイ方法

### GCP Cloud Run（推奨）

#### 1. 事前準備

```bash
# Google Cloud SDKでログイン
gcloud auth login

# プロジェクトを設定
gcloud config set project YOUR_PROJECT_ID

# 必要なAPIを有効化
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable aiplatform.googleapis.com
```

#### 2. 自動デプロイ

```bash
# デプロイスクリプトを実行
./deploy.sh YOUR_PROJECT_ID

# 環境変数を設定
./setup-env.sh YOUR_PROJECT_ID
```

#### 3. 手動デプロイ

```bash
# Dockerイメージをビルドしてプッシュ
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/vertex-ai-rag

# Cloud Runにデプロイ
gcloud run deploy vertex-ai-rag \
  --image gcr.io/YOUR_PROJECT_ID/vertex-ai-rag \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600
```

### その他のデプロイ方法

詳細なデプロイ手順は [DEPLOYMENT.md](DEPLOYMENT.md) を参照してください。

## 環境変数

| 変数名 | 説明 | 必須 | デフォルト値 |
|--------|------|------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCPプロジェクトID | ✅ | - |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | サービスアカウントキーのJSON | ✅ | - |
| `RAG_CORPUS` | RAGコーパスのリソース名 | ✅ | - |
| `GEMINI_MODEL` | 使用するGeminiモデル | ✅ | gemini-2.5-flash |
| `AUTH_USERNAME` | 基本認証のユーザー名 | ✅ | admin |
| `AUTH_PASSWORD` | 基本認証のパスワード | ✅ | password123 |

## ローカル開発

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env`ファイルを作成し、必要な環境変数を設定してください：

```env
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_APPLICATION_CREDENTIALS_JSON={"type": "service_account", ...}
RAG_CORPUS=projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id
GEMINI_MODEL=gemini-2.5-flash
AUTH_USERNAME=admin
AUTH_PASSWORD=password123
```

### 3. アプリケーションの起動

```bash
python app.py
```

アプリケーションは `http://localhost:8080` で起動します。

## API エンドポイント

### POST /chat

チャットメッセージを送信して回答を取得します。

**リクエスト:**
```json
{
  "message": "質問内容",
  "deep_mode": false
}
```

**レスポンス:**
Server-Sent Events形式でストリーミングされます。

```json
{
  "chunk": "回答の一部",
  "done": false,
  "grounding_metadata": {
    "grounding_chunks": [
      {
        "title": "ドキュメントタイトル",
        "uri": "ドキュメントURI"
      }
    ]
  }
}
```

## 機能詳細

### 通常モード

- 単一のRAGクエリを実行
- リアルタイムで回答をストリーミング
- 出典情報を表示

### 深掘りモード

1. **調査計画の立案**: 質問に対する包括的な調査計画を生成
2. **関連質問の生成**: 元の質問に関連する5つの質問を自動生成
3. **詳細調査**: 各関連質問に対してRAGクエリを実行
4. **包括的回答の統合**: 全ての調査結果を統合して包括的な回答を生成
5. **出典情報の整理**: 全ての出典情報を日付順にソートして表示

## セキュリティ

- 基本認証によるアクセス制御
- サービスアカウントキーの安全な管理
- HTTPS通信の強制（Cloud Run）

## トラブルシューティング

### よくある問題

1. **認証エラー**
   - サービスアカウントキーが正しく設定されているか確認
   - 必要な権限が付与されているか確認

2. **RAGコーパスが見つからない**
   - RAG_CORPUSの値が正しいか確認
   - コーパスが存在するか確認

3. **メモリ不足**
   - Cloud Runのメモリ設定を増やす（2Gi → 4Gi）

詳細なトラブルシューティングは [DEPLOYMENT.md](DEPLOYMENT.md) を参照してください。

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。詳細は [LICENSE](LICENSE) ファイルを参照してください。

## 貢献

プルリクエストやイシューの報告を歓迎します。貢献する前に、既存のイシューを確認してください。

## 更新履歴

- **v1.0.0**: 初期リリース
  - RAG機能の実装
  - 深掘りモードの追加
  - GCP Cloud Run対応
  - 基本認証の実装 