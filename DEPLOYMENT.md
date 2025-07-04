# GCP デプロイ手順

このドキュメントでは、Vertex AI RAGアプリケーションをGCP上にデプロイする手順を説明します。

## 前提条件

1. **Google Cloud SDK**がインストールされていること
2. **Docker**がインストールされていること（ローカルビルドの場合）
3. **GCPプロジェクト**が作成されていること
4. **適切な権限**が付与されていること

## デプロイ方法

### 方法1: Cloud Run（推奨）

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

#### 2. 自動デプロイスクリプトを使用

```bash
# デプロイスクリプトを実行
./deploy.sh YOUR_PROJECT_ID
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

### 方法2: App Engine

```bash
# App Engineにデプロイ
gcloud app deploy app.yaml
```

### 方法3: Cloud Build（CI/CD）

```bash
# Cloud Buildを使用してデプロイ
gcloud builds submit --config cloudbuild.yaml
```

## 環境変数の設定

デプロイ後、以下の環境変数を設定してください：

### Cloud Runの場合

```bash
gcloud run services update vertex-ai-rag \
  --region us-central1 \
  --set-env-vars "GOOGLE_APPLICATION_CREDENTIALS_JSON=YOUR_SERVICE_ACCOUNT_JSON" \
  --set-env-vars "RAG_CORPUS=YOUR_RAG_CORPUS_ID" \
  --set-env-vars "AUTH_USERNAME=YOUR_USERNAME" \
  --set-env-vars "AUTH_PASSWORD=YOUR_PASSWORD"
```

### App Engineの場合

`app.yaml`ファイルに環境変数を追加：

```yaml
env_variables:
  GOOGLE_APPLICATION_CREDENTIALS_JSON: "YOUR_SERVICE_ACCOUNT_JSON"
  RAG_CORPUS: "YOUR_RAG_CORPUS_ID"
  AUTH_USERNAME: "YOUR_USERNAME"
  AUTH_PASSWORD: "YOUR_PASSWORD"
```

## 必要な環境変数

| 変数名 | 説明 | 必須 |
|--------|------|------|
| `GOOGLE_CLOUD_PROJECT` | GCPプロジェクトID | ✅ |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | サービスアカウントキーのJSON | ✅ |
| `RAG_CORPUS` | RAGコーパスのリソース名 | ✅ |
| `GEMINI_MODEL` | 使用するGeminiモデル | ✅ |
| `AUTH_USERNAME` | 基本認証のユーザー名 | ✅ |
| `AUTH_PASSWORD` | 基本認証のパスワード | ✅ |

## サービスアカウントの設定

1. **サービスアカウントを作成**
   ```bash
   gcloud iam service-accounts create vertex-ai-rag \
     --display-name="Vertex AI RAG Service Account"
   ```

2. **必要な権限を付与**
   ```bash
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:vertex-ai-rag@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/aiplatform.user"
   ```

3. **キーを生成**
   ```bash
   gcloud iam service-accounts keys create key.json \
     --iam-account=vertex-ai-rag@YOUR_PROJECT_ID.iam.gserviceaccount.com
   ```

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

4. **タイムアウト**
   - タイムアウト設定を増やす（3600秒）

### ログの確認

```bash
# Cloud Runのログを確認
gcloud logs read --service=vertex-ai-rag --limit=50

# App Engineのログを確認
gcloud app logs tail -s vertex-ai-rag
```

## セキュリティ考慮事項

1. **認証情報の管理**
   - サービスアカウントキーは環境変数として設定
   - リポジトリにコミットしない

2. **ネットワークセキュリティ**
   - 必要に応じてVPCコネクタを使用
   - 適切なIAM権限を設定

3. **HTTPS**
   - Cloud Runは自動的にHTTPSを提供
   - カスタムドメインを使用する場合はSSL証明書を設定

## コスト最適化

1. **スケーリング設定**
   - 最小インスタンス数を0に設定
   - 適切な最大インスタンス数を設定

2. **リソース設定**
   - 必要最小限のCPU/メモリを設定
   - 使用状況に応じて調整

## 監視とアラート

1. **Cloud Monitoring**
   - エラー率の監視
   - レスポンス時間の監視
   - リソース使用率の監視

2. **アラート設定**
   - エラー率が閾値を超えた場合
   - レスポンス時間が長い場合
   - リソース使用率が高い場合 