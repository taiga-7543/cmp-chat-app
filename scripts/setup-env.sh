#!/bin/bash

# エラー時に停止
set -e

# 設定
PROJECT_ID=${1:-"dotd-development-division"}
REGION="us-central1"
SERVICE_NAME="vertex-ai-rag"

echo "🔧 環境変数を設定します..."
echo "📋 プロジェクトID: $PROJECT_ID"
echo "🌍 リージョン: $REGION"
echo "🔧 サービス名: $SERVICE_NAME"

# サービスアカウントキーファイルの確認
if [ ! -f "rag-service-account-key.json" ]; then
    echo "❌ サービスアカウントキーファイルが見つかりません: rag-service-account-key.json"
    echo "📝 サービスアカウントキーを作成してください:"
    echo "   gcloud iam service-accounts keys create rag-service-account-key.json \\"
    echo "     --iam-account=rag-test@$PROJECT_ID.iam.gserviceaccount.com"
    exit 1
fi

# サービスアカウントキーをJSON文字列として読み込み
SERVICE_ACCOUNT_JSON=$(cat rag-service-account-key.json | tr -d '\n' | tr -d ' ')

# .envファイルからRAG_CORPUSを読み込み
if [ -f ".env" ]; then
    RAG_CORPUS=$(grep "RAG_CORPUS=" .env | cut -d'=' -f2)
    AUTH_USERNAME=$(grep "AUTH_USERNAME=" .env | cut -d'=' -f2)
    AUTH_PASSWORD=$(grep "AUTH_PASSWORD=" .env | cut -d'=' -f2)
else
    echo "⚠️  .envファイルが見つかりません。デフォルト値を使用します。"
    RAG_CORPUS="projects/$PROJECT_ID/locations/us-central1/ragCorpora/3458764513820540928"
    AUTH_USERNAME="admin"
    AUTH_PASSWORD="password123"
fi

echo "📝 環境変数を設定中..."

# Cloud Runの環境変数を更新
gcloud run services update $SERVICE_NAME \
  --region $REGION \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --set-env-vars "GOOGLE_APPLICATION_CREDENTIALS_JSON=$SERVICE_ACCOUNT_JSON" \
  --set-env-vars "RAG_CORPUS=$RAG_CORPUS" \
  --set-env-vars "GEMINI_MODEL=gemini-2.5-flash" \
  --set-env-vars "AUTH_USERNAME=$AUTH_USERNAME" \
  --set-env-vars "AUTH_PASSWORD=$AUTH_PASSWORD"

echo "✅ 環境変数の設定が完了しました！"

echo ""
echo "📋 設定された環境変数:"
echo "  - GOOGLE_CLOUD_PROJECT: $PROJECT_ID"
echo "  - RAG_CORPUS: $RAG_CORPUS"
echo "  - GEMINI_MODEL: gemini-2.5-flash"
echo "  - AUTH_USERNAME: $AUTH_USERNAME"
echo "  - AUTH_PASSWORD: $AUTH_PASSWORD"

echo ""
echo "🌐 サービスURL:"
gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"

echo ""
echo "🔍 サービスが正常に動作しているか確認するには:"
echo "   curl -u $AUTH_USERNAME:$AUTH_PASSWORD \$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')" 