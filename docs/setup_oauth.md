# Google OAuth 2.0 設定手順

## 1. Google Cloud Console設定

### OAuth 2.0クライアントID作成
1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. プロジェクト `dotd-development-division` を選択
3. **APIとサービス** → **認証情報** に移動
4. **+ 認証情報を作成** → **OAuth 2.0 クライアントID** を選択

### アプリケーションタイプ設定
- **アプリケーションの種類**: `ウェブアプリケーション`
- **名前**: `CMP Chat App - Drive Sync`

### 承認済みリダイレクトURI
```
http://localhost:8080/auth/google/callback
https://your-app-domain.com/auth/google/callback  # 本番環境用
```

### client_secrets.json ダウンロード
- 作成後、**JSONをダウンロード**
- ファイル名を `client_secrets.json` に変更
- プロジェクトルートに配置

## 2. 必要なAPIの有効化

```bash
# Google Drive API有効化
gcloud services enable drive.googleapis.com --project=dotd-development-division

# 既に有効化済みのAPI確認
gcloud services list --enabled --project=dotd-development-division
```

## 3. 環境変数設定

`.env` ファイルに追加:
```bash
# OAuth設定
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=client_secrets.json
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform

# Drive同期設定
DRIVE_SYNC_FOLDER_NAME=RAG Documents
DRIVE_SYNC_ENABLED=true
```

## 4. 依存関係追加

`requirements.txt` に追加:
```
google-auth-oauthlib>=1.0.0
```

インストール:
```bash
pip install google-auth-oauthlib
```