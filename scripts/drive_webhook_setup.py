"""
Google Drive Push Notifications (Webhooks) の設定
"""

import os
import json
import uuid
from typing import Dict, Optional
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

class DriveWebhookManager:
    """Google Drive Webhook管理クラス"""
    
    def __init__(self, credentials_info: Dict):
        """
        初期化
        
        Args:
            credentials_info: サービスアカウント情報
        """
        self.credentials = ServiceAccountCredentials.from_service_account_info(
            credentials_info,
            scopes=[
                'https://www.googleapis.com/auth/drive.readonly',
                'https://www.googleapis.com/auth/drive.metadata.readonly'
            ]
        )
        
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
    
    def setup_folder_watch(self, 
                          folder_id: str, 
                          webhook_url: str,
                          channel_id: Optional[str] = None) -> Dict:
        """
        フォルダの変更監視を設定
        
        Args:
            folder_id: 監視するフォルダID
            webhook_url: Webhook URL（Cloud Functions等）
            channel_id: チャンネルID（省略時は自動生成）
        
        Returns:
            チャンネル情報
        """
        if not channel_id:
            channel_id = str(uuid.uuid4())
        
        # Push notification設定
        body = {
            'id': channel_id,
            'type': 'web_hook',
            'address': webhook_url,
            'payload': True,  # 変更内容も含める
            'params': {
                'ttl': '86400'  # 24時間（秒）
            }
        }
        
        try:
            # フォルダの変更監視を開始
            channel = self.drive_service.files().watch(
                fileId=folder_id,
                body=body
            ).execute()
            
            print(f"Webhook設定完了:")
            print(f"  Channel ID: {channel['id']}")
            print(f"  Resource ID: {channel['resourceId']}")
            print(f"  Expiration: {channel.get('expiration', 'N/A')}")
            
            return channel
            
        except Exception as e:
            print(f"Webhook設定エラー: {e}")
            raise
    
    def stop_channel(self, channel_id: str, resource_id: str):
        """
        チャンネルを停止
        
        Args:
            channel_id: チャンネルID
            resource_id: リソースID
        """
        try:
            self.drive_service.channels().stop(
                body={
                    'id': channel_id,
                    'resourceId': resource_id
                }
            ).execute()
            
            print(f"チャンネル停止完了: {channel_id}")
            
        except Exception as e:
            print(f"チャンネル停止エラー: {e}")
    
    def list_changes(self, folder_id: str, page_token: Optional[str] = None) -> Dict:
        """
        フォルダの変更一覧を取得
        
        Args:
            folder_id: フォルダID
            page_token: ページトークン
        
        Returns:
            変更情報
        """
        try:
            # 初回の場合はstartPageTokenを取得
            if not page_token:
                start_page_token = self.drive_service.changes().getStartPageToken().execute()
                page_token = start_page_token.get('startPageToken')
            
            # 変更一覧を取得
            changes = self.drive_service.changes().list(
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="nextPageToken,newStartPageToken,changes(fileId,file(id,name,mimeType,parents,modifiedTime,trashed))"
            ).execute()
            
            return changes
            
        except Exception as e:
            print(f"変更一覧取得エラー: {e}")
            return {}


# Cloud Functions用のWebhookハンドラー
def handle_drive_webhook(request):
    """
    Google Drive Webhookを処理するCloud Functions
    
    Args:
        request: Flask Request オブジェクト
    
    Returns:
        レスポンス
    """
    import functions_framework
    from flask import jsonify
    
    # Webhookの検証
    if request.method == 'POST':
        # ヘッダーから情報を取得
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        resource_state = request.headers.get('X-Goog-Resource-State')
        
        print(f"Webhook受信:")
        print(f"  Channel ID: {channel_id}")
        print(f"  Resource ID: {resource_id}")
        print(f"  State: {resource_state}")
        
        # 同期処理をトリガー
        if resource_state in ['update', 'add', 'remove']:
            trigger_sync_process(channel_id, resource_id, resource_state)
        
        return jsonify({'status': 'ok'}), 200
    
    return jsonify({'error': 'Invalid request'}), 400


def trigger_sync_process(channel_id: str, resource_id: str, state: str):
    """
    同期処理をトリガー
    
    Args:
        channel_id: チャンネルID
        resource_id: リソースID
        state: 変更状態
    """
    try:
        # 環境変数から設定を読み込み
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        
        if not credentials_json:
            print("認証情報が設定されていません")
            return
        
        # 同期処理を実行
        from google_drive_sync import create_sync_instance
        
        sync = create_sync_instance(
            project_id=project_id,
            credentials_json=credentials_json
        )
        
        # 変更されたファイルのみを同期
        # （実際の実装では、変更されたファイルを特定して処理）
        print(f"同期処理を開始: {state}")
        
        # ここで実際の同期ロジックを呼び出し
        # sync.sync_changed_files(...)
        
    except Exception as e:
        print(f"同期処理エラー: {e}")


# 設定用スクリプト
if __name__ == "__main__":
    # 環境変数から設定を読み込み
    CREDENTIALS_JSON = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')  # 監視するフォルダID
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL')    # Cloud FunctionsのURL
    
    if not all([CREDENTIALS_JSON, FOLDER_ID, WEBHOOK_URL]):
        print("必要な環境変数が設定されていません")
        exit(1)
    
    try:
        credentials_info = json.loads(CREDENTIALS_JSON)
        webhook_manager = DriveWebhookManager(credentials_info)
        
        # Webhook設定
        channel = webhook_manager.setup_folder_watch(
            folder_id=FOLDER_ID,
            webhook_url=WEBHOOK_URL
        )
        
        # チャンネル情報を保存（後で停止するため）
        with open('webhook_channels.json', 'w') as f:
            json.dump([channel], f, indent=2)
        
        print("Webhook設定が完了しました")
        
    except Exception as e:
        print(f"設定エラー: {e}")