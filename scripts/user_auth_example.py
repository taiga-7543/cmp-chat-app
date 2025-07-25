"""
ユーザーアカウント認証を使用したGoogle Drive同期の例
"""

import os
import json
from typing import Optional, Dict
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import pickle

class UserAuthDriveSync:
    """ユーザー認証を使用したGoogle Drive同期"""
    
    def __init__(self, client_secrets_file: str, token_file: str = 'token.pickle'):
        """
        初期化
        
        Args:
            client_secrets_file: OAuth 2.0クライアント設定ファイル
            token_file: トークン保存ファイル
        """
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        self.scopes = [
            'https://www.googleapis.com/auth/drive.readonly',
            'https://www.googleapis.com/auth/cloud-platform'
        ]
        self.credentials = None
        self.drive_service = None
    
    def authenticate(self) -> bool:
        """
        ユーザー認証を実行
        
        Returns:
            認証成功かどうか
        """
        # 既存のトークンを読み込み
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                self.credentials = pickle.load(token)
        
        # トークンが無効または期限切れの場合
        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                # リフレッシュトークンで更新
                try:
                    self.credentials.refresh(Request())
                    print("トークンを更新しました")
                except Exception as e:
                    print(f"トークン更新エラー: {e}")
                    self.credentials = None
            
            # 新規認証が必要
            if not self.credentials:
                flow = Flow.from_client_secrets_file(
                    self.client_secrets_file,
                    scopes=self.scopes
                )
                flow.redirect_uri = 'http://localhost:8080/callback'
                
                # 認証URLを生成
                auth_url, _ = flow.authorization_url(
                    access_type='offline',
                    include_granted_scopes='true'
                )
                
                print(f"以下のURLにアクセスして認証してください:")
                print(auth_url)
                
                # 認証コードを入力
                auth_code = input("認証コードを入力してください: ")
                
                try:
                    flow.fetch_token(code=auth_code)
                    self.credentials = flow.credentials
                    print("認証が完了しました")
                except Exception as e:
                    print(f"認証エラー: {e}")
                    return False
            
            # トークンを保存
            with open(self.token_file, 'wb') as token:
                pickle.dump(self.credentials, token)
        
        # Drive APIサービスを初期化
        try:
            self.drive_service = build('drive', 'v3', credentials=self.credentials)
            return True
        except Exception as e:
            print(f"Drive API初期化エラー: {e}")
            return False
    
    def get_user_info(self) -> Optional[Dict]:
        """
        認証されたユーザーの情報を取得
        
        Returns:
            ユーザー情報
        """
        if not self.drive_service:
            return None
        
        try:
            about = self.drive_service.about().get(fields="user").execute()
            return about.get('user', {})
        except Exception as e:
            print(f"ユーザー情報取得エラー: {e}")
            return None
    
    def list_user_files(self, folder_name: Optional[str] = None) -> list:
        """
        ユーザーのファイル一覧を取得
        
        Args:
            folder_name: フォルダ名（省略時は全ファイル）
        
        Returns:
            ファイル一覧
        """
        if not self.drive_service:
            return []
        
        try:
            query = "trashed=false"
            
            # フォルダ指定がある場合
            if folder_name:
                # フォルダを検索
                folder_query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
                folder_results = self.drive_service.files().list(
                    q=folder_query,
                    fields="files(id, name)"
                ).execute()
                
                folders = folder_results.get('files', [])
                if folders:
                    folder_id = folders[0]['id']
                    query += f" and parents in '{folder_id}'"
                else:
                    print(f"フォルダが見つかりません: {folder_name}")
                    return []
            
            # ファイル一覧を取得
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink)",
                pageSize=100
            ).execute()
            
            return results.get('files', [])
            
        except Exception as e:
            print(f"ファイル一覧取得エラー: {e}")
            return []


# Flask統合の例
def integrate_with_flask_app():
    """既存のFlaskアプリに統合する例"""
    
    from flask import session, redirect, url_for, request
    
    # app.pyに追加するルート例
    """
    @app.route('/auth/google')
    @auth.login_required
    def google_auth():
        # OAuth認証開始
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        flow.redirect_uri = url_for('google_callback', _external=True)
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        
        session['state'] = state
        return redirect(authorization_url)
    
    @app.route('/auth/google/callback')
    @auth.login_required
    def google_callback():
        # OAuth認証コールバック
        state = session['state']
        
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/drive.readonly'],
            state=state
        )
        flow.redirect_uri = url_for('google_callback', _external=True)
        
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        
        # 認証情報を保存
        credentials = flow.credentials
        session['google_credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        return redirect(url_for('index'))
    
    @app.route('/sync/drive')
    @auth.login_required
    def sync_drive():
        # Google Drive同期実行
        if 'google_credentials' not in session:
            return redirect(url_for('google_auth'))
        
        # 認証情報を復元
        creds_info = session['google_credentials']
        credentials = Credentials(
            token=creds_info['token'],
            refresh_token=creds_info['refresh_token'],
            token_uri=creds_info['token_uri'],
            client_id=creds_info['client_id'],
            client_secret=creds_info['client_secret'],
            scopes=creds_info['scopes']
        )
        
        # Drive API使用
        drive_service = build('drive', 'v3', credentials=credentials)
        # ... 同期処理 ...
        
        return jsonify({'status': 'success'})
    """


if __name__ == "__main__":
    # 使用例
    sync = UserAuthDriveSync('client_secrets.json')
    
    if sync.authenticate():
        user_info = sync.get_user_info()
        print(f"認証ユーザー: {user_info.get('displayName', 'Unknown')}")
        
        files = sync.list_user_files("RAG Documents")
        print(f"ファイル数: {len(files)}")
        
        for file in files[:5]:  # 最初の5件を表示
            print(f"- {file['name']} ({file['mimeType']})")
    else:
        print("認証に失敗しました")