#!/bin/bash

# エラー時に停止
set -e

# 設定
PROJECT_ID=${1:-"dotd-development-division"}
SERVICE_ACCOUNT="rag-test@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🔐 IAM権限を設定します..."
echo "📋 プロジェクトID: $PROJECT_ID"
echo "🔧 サービスアカウント: $SERVICE_ACCOUNT"

# 1. Vertex AI ユーザー権限
echo "🤖 Vertex AI ユーザー権限を付与中..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/aiplatform.user"

# 2. Cloud Run 管理者権限
echo "🚀 Cloud Run 管理者権限を付与中..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/run.admin"

# 3. Cloud Build サービスアカウント権限
echo "🔨 Cloud Build サービスアカウント権限を付与中..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/cloudbuild.builds.builder"

# 4. サービスアカウント ユーザー権限
echo "👤 サービスアカウント ユーザー権限を付与中..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/iam.serviceAccountUser"

# 5. Storage 管理者権限
echo "📦 Storage 管理者権限を付与中..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/storage.admin"

echo "✅ 全ての権限が付与されました！"

# 付与された権限を確認
echo ""
echo "📋 付与された権限:"
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:serviceAccount:$SERVICE_ACCOUNT"

echo ""
echo "🔍 権限が反映されるまで数分かかる場合があります。" 