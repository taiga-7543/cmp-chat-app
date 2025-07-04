#!/bin/bash

# エラー時に停止
set -e

# 設定
PROJECT_ID=${1:-"dotd-development-division"}
REGION="us-central1"
SERVICE_NAME="vertex-ai-rag"

echo "🚀 GCP Cloud Run デプロイを開始します..."
echo "📋 プロジェクトID: $PROJECT_ID"
echo "🌍 リージョン: $REGION"
echo "🔧 サービス名: $SERVICE_NAME"

# プロジェクトの設定
echo "📝 プロジェクトを設定中..."
gcloud config set project $PROJECT_ID

# 必要なAPIを有効化
echo "🔌 必要なAPIを有効化中..."
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable aiplatform.googleapis.com

# Dockerイメージをビルドしてプッシュ
echo "🐳 Dockerイメージをビルド中..."
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"
gcloud builds submit --tag $IMAGE_NAME

# Cloud Runにデプロイ
echo "🚀 Cloud Runにデプロイ中..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 80 \
  --max-instances 10 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --set-env-vars "GEMINI_MODEL=gemini-2.5-flash"

# デプロイ完了
echo "✅ デプロイが完了しました！"
echo "🌐 サービスURL:"
gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"

echo ""
echo "📝 次のステップ:"
echo "1. 環境変数を設定してください（GOOGLE_APPLICATION_CREDENTIALS_JSON等）"
echo "2. RAG_CORPUSの設定を確認してください"
echo "3. 認証情報（AUTH_USERNAME, AUTH_PASSWORD）を設定してください" 