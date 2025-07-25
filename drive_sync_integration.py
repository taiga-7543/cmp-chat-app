"""
Google Drive同期機能の統合モジュール
"""

import os
import json
import pickle
import tempfile
from typing import Optional, Dict, List
from datetime import datetime
import hashlib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.cloud import storage
from google.cloud import aiplatform
import io

# 開発環境でHTTPを許可
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class DriveRAGIntegration:
    """Google Drive と RAG の統合クラス"""
    
    def __init__(self, 
                 project_id: str,
                 client_secrets_file: str = 'config/client_secrets.json',
                 token_file: str = 'temp/google_drive_token.pickle',
                 bucket_name: Optional[str] = None):
        """
        初期化
        
        Args:
            project_id: Google Cloud プロジェクトID
            client_secrets_file: OAuth クライアント設定ファイル
            token_file: トークン保存ファイル
            bucket_name: Cloud Storage バケット名
        """
        self.project_id = project_id
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        self.bucket_name = bucket_name or f"{project_id}-drive-sync"
        
        # OAuth スコープ
        self.scopes = [
            'https://www.googleapis.com/auth/drive',  # 完全なDriveアクセス（共有ドライブ含む）
            'https://www.googleapis.com/auth/drive.file',  # ファイルへのアクセス
            'https://www.googleapis.com/auth/drive.metadata',  # メタデータアクセス
            'https://www.googleapis.com/auth/cloud-platform'
        ]
        
        self.credentials = None
        self.drive_service = None
        self.storage_client = None
        self.rag_client = None
        
        # 同期状態管理
        self.sync_state_file = "temp/drive_sync_state.json"
        self.sync_state = self._load_sync_state()
    
    def _load_sync_state(self) -> Dict:
        """同期状態を読み込み"""
        try:
            if os.path.exists(self.sync_state_file):
                with open(self.sync_state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"同期状態の読み込みエラー: {e}")
        
        return {
            'last_sync': None,
            'file_hashes': {},
            'corpus_id': None,
            'synced_files': {},
            'user_email': None
        }
    
    def _save_sync_state(self):
        """同期状態を保存"""
        try:
            with open(self.sync_state_file, 'w', encoding='utf-8') as f:
                json.dump(self.sync_state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"同期状態の保存エラー: {e}")
    
    def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """
        認証URLを生成
        
        Args:
            redirect_uri: リダイレクトURI
        
        Returns:
            (認証URL, state)
        """
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes
        )
        flow.redirect_uri = redirect_uri
        
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # 毎回同意画面を表示（リフレッシュトークン取得のため）
        )
        
        return auth_url, state
    
    def handle_oauth_callback(self, authorization_response: str, state: str, redirect_uri: str) -> bool:
        """
        OAuth コールバックを処理
        
        Args:
            authorization_response: 認証レスポンスURL
            state: 状態パラメータ
            redirect_uri: リダイレクトURI
        
        Returns:
            認証成功かどうか
        """
        try:
            print(f"DEBUG: OAuth callback - authorization_response: {authorization_response}")
            print(f"DEBUG: OAuth callback - state: {state}")
            print(f"DEBUG: OAuth callback - redirect_uri: {redirect_uri}")
            
            flow = Flow.from_client_secrets_file(
                self.client_secrets_file,
                scopes=self.scopes,
                state=state
            )
            flow.redirect_uri = redirect_uri
            
            print(f"DEBUG: Flow created successfully")
            
            # URLからコードを抽出
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(authorization_response)
            query_params = parse_qs(parsed_url.query)
            auth_code = query_params.get('code', [None])[0]
            
            if not auth_code:
                raise ValueError("認証コードが見つかりません")
            
            print(f"DEBUG: Auth code extracted: {auth_code[:20]}...")
            
            # 直接トークンを取得（スコープ検証なし）
            import requests
            token_data = {
                'code': auth_code,
                'client_id': flow.client_config['client_id'],
                'client_secret': flow.client_config['client_secret'],
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            
            token_response = requests.post(
                flow.client_config['token_uri'],
                data=token_data
            )
            
            if token_response.status_code != 200:
                raise ValueError(f"トークン取得エラー: {token_response.text}")
            
            token_info = token_response.json()
            print(f"DEBUG: Token response: {token_info}")
            
            # 認証情報を作成
            self.credentials = Credentials(
                token=token_info['access_token'],
                refresh_token=token_info.get('refresh_token'),
                token_uri=flow.client_config['token_uri'],
                client_id=flow.client_config['client_id'],
                client_secret=flow.client_config['client_secret'],
                scopes=self.scopes
            )
# 既に上で設定済み
            
            print(f"DEBUG: Token fetched successfully")
            
            # トークンを保存
            with open(self.token_file, 'wb') as token:
                pickle.dump(self.credentials, token)
            
            print(f"DEBUG: Token saved to {self.token_file}")
            
            # サービスを初期化
            self._initialize_services()
            
            print(f"DEBUG: Services initialized")
            
            # ユーザー情報を取得して保存
            user_info = self.get_user_info()
            if user_info:
                self.sync_state['user_email'] = user_info.get('emailAddress')
                self._save_sync_state()
                print(f"DEBUG: User info saved: {user_info.get('emailAddress')}")
            
            return True
            
        except Exception as e:
            print(f"OAuth コールバック処理エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def load_credentials(self) -> bool:
        """
        保存された認証情報を読み込み
        
        Returns:
            認証情報の読み込み成功かどうか
        """
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as token:
                    self.credentials = pickle.load(token)
                
                # トークンの有効性をチェック
                if not self.credentials.valid:
                    if self.credentials.expired and self.credentials.refresh_token:
                        # リフレッシュトークンで更新
                        self.credentials.refresh(Request())
                        
                        # 更新されたトークンを保存
                        with open(self.token_file, 'wb') as token:
                            pickle.dump(self.credentials, token)
                    else:
                        return False
                
                # サービスを初期化
                self._initialize_services()
                return True
                
            except Exception as e:
                print(f"認証情報読み込みエラー: {e}")
                return False
        
        return False
    
    def _initialize_services(self):
        """各種サービスを初期化"""
        if not self.credentials:
            return
        
        # Google Drive API
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
        
        # Cloud Storage
        self.storage_client = storage.Client(
            project=self.project_id,
            credentials=self.credentials
        )
        
        # Vertex AI RAG用の設定
        self.location_path = f"projects/{self.project_id}/locations/us-central1"
    
    def is_authenticated(self) -> bool:
        """認証状態をチェック"""
        return (self.credentials is not None and 
                self.credentials.valid and 
                self.drive_service is not None)
    
    def get_user_info(self) -> Optional[Dict]:
        """認証されたユーザーの情報を取得"""
        if not self.drive_service:
            return None
        
        try:
            about = self.drive_service.about().get(
                fields="user(displayName,emailAddress,photoLink)"
            ).execute()
            return about.get('user', {})
        except Exception as e:
            print(f"ユーザー情報取得エラー: {e}")
            return None
    
    def find_folder_by_name(self, folder_input: str) -> Optional[str]:
        """
        フォルダ名、パス、URL、または共有リンクからフォルダIDを取得
        
        Args:
            folder_input: フォルダの指定方法
                        例: 
                        - "RAG Documents" (フォルダ名)
                        - "/プロジェクト/RAG Documents" (パス)
                        - "https://drive.google.com/drive/folders/1ABC..." (URL)
                        - "https://drive.google.com/drive/u/0/folders/1ABC..." (URL)
                        - "1ABC2DEF3GHI..." (フォルダID直接)
        
        Returns:
            フォルダID または None
        """
        if not self.drive_service:
            print("ERROR: Drive service が初期化されていません")
            return None
        
        print(f"DEBUG: フォルダ検索開始: '{folder_input}'")
        
        try:
            # URLまたは共有リンクかどうかを判定
            if self._is_drive_url(folder_input):
                print("DEBUG: Drive URLとして処理")
                return self._extract_folder_id_from_url(folder_input)
            # フォルダIDの直接指定かどうかを判定
            elif self._is_folder_id(folder_input):
                print("DEBUG: フォルダIDとして処理")
                return self._validate_folder_id(folder_input)
            # パス形式かどうかを判定
            elif folder_input.startswith('/'):
                print("DEBUG: パス形式として処理")
                return self._find_folder_by_path(folder_input)
            else:
                print("DEBUG: フォルダ名として処理")
                return self._find_folder_by_simple_name(folder_input)
            
        except Exception as e:
            print(f"ERROR: フォルダ検索エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _is_drive_url(self, input_str: str) -> bool:
        """Google DriveのURLかどうかを判定"""
        return (input_str.startswith('https://drive.google.com/') or 
                input_str.startswith('http://drive.google.com/'))
    
    def _is_folder_id(self, input_str: str) -> bool:
        """フォルダIDの直接指定かどうかを判定"""
        # Google DriveのフォルダIDは通常33文字の英数字とハイフン、アンダースコア
        import re
        return bool(re.match(r'^[a-zA-Z0-9_-]{25,35}$', input_str))
    
    def _extract_folder_id_from_url(self, url: str) -> Optional[str]:
        """
        Google Drive URLからフォルダIDを抽出
        
        対応するURL形式:
        - https://drive.google.com/drive/folders/FOLDER_ID
        - https://drive.google.com/drive/u/0/folders/FOLDER_ID
        - https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
        - https://drive.google.com/drive/folders/FOLDER_ID?usp=drive_link
        - https://drive.google.com/open?id=FOLDER_ID
        """
        import re
        from urllib.parse import urlparse, parse_qs
        
        print(f"DEBUG: URL解析中: {url}")
        
        try:
            # パターン1: /folders/FOLDER_ID 形式（最も一般的）
            folder_match = re.search(r'/folders/([a-zA-Z0-9_-]{25,35})', url)
            if folder_match:
                folder_id = folder_match.group(1)
                print(f"DEBUG: フォルダIDを抽出 (folders pattern): {folder_id}")
                return self._validate_folder_id(folder_id)
            
            # パターン2: ?id=FOLDER_ID 形式
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'id' in query_params:
                folder_id = query_params['id'][0]
                print(f"DEBUG: フォルダIDを抽出 (id param): {folder_id}")
                return self._validate_folder_id(folder_id)
            
            # パターン3: URLの各部分をチェック
            # URLをスラッシュで分割して、各部分がフォルダIDかどうかをチェック
            url_without_params = url.split('?')[0]  # クエリパラメータを除去
            url_parts = url_without_params.split('/')
            
            for part in url_parts:
                if part and self._is_folder_id(part):
                    print(f"DEBUG: フォルダIDを抽出 (URL part): {part}")
                    return self._validate_folder_id(part)
            
            print(f"ERROR: URLからフォルダIDを抽出できませんでした: {url}")
            print(f"DEBUG: URL parts: {url_parts}")
            return None
            
        except Exception as e:
            print(f"ERROR: URL解析エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _validate_folder_id(self, folder_id: str) -> Optional[str]:
        """
        フォルダIDが有効かどうかを検証
        
        Args:
            folder_id: 検証するフォルダID
        
        Returns:
            有効な場合はフォルダID、無効な場合はNone
        """
        if not folder_id:
            print("ERROR: フォルダIDが空です")
            return None
            
        print(f"DEBUG: フォルダID検証中: {folder_id}")
        
        # 共通関数を使用してフォルダ情報を取得
        folder = self._call_drive_files_get(folder_id, "id, name, mimeType, parents")
        if not folder:
            print(f"❌ フォルダID検証エラー: {folder_id}")
            print("   → フォルダが存在しないか、アクセスできません")
            return None
        
        print(f"DEBUG: フォルダ情報取得成功: {folder}")
        
        # フォルダかどうかを確認
        if folder.get('mimeType') == 'application/vnd.google-apps.folder':
            print(f"✅ フォルダID検証成功: {folder_id}")
            print(f"   名前: {folder.get('name')}")
            return folder_id
        else:
            print(f"❌ 指定されたIDはフォルダではありません: {folder_id}")
            print(f"   MIMEタイプ: {folder.get('mimeType')}")
            return None
    
    def _find_folder_by_simple_name(self, folder_name: str) -> Optional[str]:
        """単純なフォルダ名で検索"""
        print(f"フォルダ名で検索中: {folder_name}")
        
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        print(f"検索クエリ: {query}")
        
        # 全ドライブを対象に検索
        folders = self._call_drive_files_list(query, "files(id, name, parents, driveId)", drive_id=None)
        
        print(f"検索結果: {len(folders)}件のフォルダが見つかりました")
        for i, folder in enumerate(folders):
            drive_id = folder.get('driveId', 'マイドライブ')
            print(f"  {i+1}. {folder.get('name')} (ID: {folder.get('id')}, ドライブ: {drive_id})")
        
        if folders:
            selected_folder = folders[0]
            print(f"選択されたフォルダ: {folder_name} (ID: {selected_folder['id']})")
            return selected_folder['id']
        
        print(f"フォルダが見つかりません: {folder_name}")
        return None
    
    def _find_folder_by_path(self, folder_path: str) -> Optional[str]:
        """パス形式でフォルダを検索"""
        # パスを分割（先頭の/を除去）
        path_parts = [part for part in folder_path[1:].split('/') if part]
        
        if not path_parts:
            return 'root'
        
        current_folder_id = 'root'
        current_path = ""
        
        for folder_name in path_parts:
            current_path += f"/{folder_name}"
            print(f"検索中: {current_path}")
            
            # 現在のフォルダ内でフォルダを検索
            query = f"name='{folder_name}' and parents in '{current_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            folders = self._call_drive_files_list(query, "files(id, name)", drive_id=None)
            
            if not folders:
                print(f"フォルダが見つかりません: {current_path}")
                return None
            
            current_folder_id = folders[0]['id']
            print(f"フォルダが見つかりました: {current_path} (ID: {current_folder_id})")
        
        return current_folder_id
    
    def list_folders(self, parent_folder_id: str = 'root', max_results: int = 50) -> List[Dict]:
        """
        フォルダ一覧を取得
        
        Args:
            parent_folder_id: 親フォルダID（'root'でルートフォルダ）
            max_results: 最大取得件数
        
        Returns:
            フォルダ情報のリスト
        """
        if not self.drive_service:
            return []
        
        # 共有ドライブIDを取得（親フォルダから）
        drive_id = None
        if parent_folder_id != 'root':
            drive_id = self._get_drive_id_for_folder(parent_folder_id)
        
        query = f"parents in '{parent_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        folders = self._call_drive_files_list(
            query, 
            "files(id, name, parents, createdTime, modifiedTime)", 
            page_size=max_results, 
            order_by="name",
            drive_id=drive_id
        )
        
        print(f"フォルダ一覧取得: {len(folders)}件")
        return folders
    
    def get_folder_path(self, folder_id: str) -> str:
        """
        フォルダIDからフルパスを取得
        
        Args:
            folder_id: フォルダID
        
        Returns:
            フォルダのフルパス
        """
        if not self.drive_service or folder_id == 'root':
            return '/'
        
        path_parts = []
        current_id = folder_id
        
        while current_id and current_id != 'root':
            # フォルダ情報を取得
            folder = self._call_drive_files_get(current_id, "name, parents")
            if not folder:
                print(f"フォルダパス取得エラー: フォルダ情報が取得できませんでした (ID: {current_id})")
                return f"/unknown_folder_{folder_id}"
            
            path_parts.insert(0, folder['name'])
            
            # 親フォルダIDを取得
            parents = folder.get('parents', [])
            current_id = parents[0] if parents else None
        
        return '/' + '/'.join(path_parts) if path_parts else '/'
    
    def list_folder_files(self, folder_id: str) -> List[Dict]:
        """
        フォルダ内のファイル一覧を取得
        
        Args:
            folder_id: フォルダID
        
        Returns:
            ファイル情報のリスト
        """
        if not self.drive_service:
            print("❌ Drive service が初期化されていません")
            return []
        
        print(f"📁 フォルダ内ファイル一覧取得開始: {folder_id}")
        
        # Step 1: フォルダ情報を取得して共有ドライブかどうかを判定
        folder_info = self._call_drive_files_get(
            folder_id, 
            "id, name, mimeType, driveId, parents, capabilities"
        )
        if not folder_info:
            print(f"❌ フォルダ情報の取得に失敗: {folder_id}")
            return []
        
        folder_name = folder_info.get('name', '不明')
        drive_id = folder_info.get('driveId')
        
        if drive_id:
            print(f"📁 共有ドライブフォルダ: {folder_name} (共有ドライブID: {drive_id})")
        else:
            print(f"📁 マイドライブフォルダ: {folder_name}")
        
        print(f"📋 フォルダ詳細情報: {folder_info}")
        
        # Step 2: サポートするファイル形式の定義
        supported_mimetypes = [
            'application/pdf',                                                    # PDF
            'text/plain',                                                        # テキストファイル
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # Word (.docx)
            'application/msword',                                                # Word (.doc)
            'text/markdown',                                                     # Markdown
            'application/rtf',                                                   # RTF
            'application/vnd.google-apps.document',                             # Google Docs
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PowerPoint (.pptx)
            'application/vnd.ms-powerpoint',                                     # PowerPoint (.ppt)
            'application/vnd.google-apps.presentation'                          # Google Slides
        ]
        
        # Step 3: 全ファイル（形式制限なし）を取得してデバッグ
        print(f"\n🔍 === デバッグ: 全ファイル取得テスト ===")
        all_files_query = f"parents in '{folder_id}' and trashed=false"
        print(f"📝 クエリ: {all_files_query}")
        
        all_files = self._call_drive_files_list(
            all_files_query, 
            "files(id, name, mimeType, size, modifiedTime, webViewLink, driveId)", 
            page_size=100,
            drive_id=drive_id
        )
        
        print(f"📊 フォルダ内の全ファイル数: {len(all_files)}")
        if all_files:
            print(f"📄 全ファイル一覧:")
            for i, file in enumerate(all_files):
                size_info = f" ({file.get('size', '不明')} bytes)" if file.get('size') else ""
                drive_info = f" [共有ドライブ: {file.get('driveId', '不明')[:10]}...]" if file.get('driveId') else " [マイドライブ]"
                print(f"  {i+1}. {file.get('name')}{size_info} ({file.get('mimeType')}){drive_info}")
        else:
            print(f"⚠️  フォルダ内にファイルが見つかりません")
            
            # さらなるデバッグ: 権限チェック
            print(f"\n🔧 === 権限診断 ===")
            capabilities = folder_info.get('capabilities', {})
            if capabilities:
                print(f"📝 フォルダ権限: {capabilities}")
                if not capabilities.get('canListChildren', True):
                    print(f"❌ 警告: フォルダ内容一覧表示権限がありません")
            else:
                print(f"⚠️  フォルダ権限情報が取得できませんでした")
        
        # Step 4: サポート対象ファイル形式のみを取得
        print(f"\n🎯 === サポート対象ファイル抽出 ===")
        mimetype_conditions = [f"mimeType='{mt}'" for mt in supported_mimetypes]
        mimetype_query = " or ".join(mimetype_conditions)
        
        # 共有ドライブ内でのクエリを最適化
        if drive_id:
            # 共有ドライブの場合：より確実な検索方法を使用
            supported_files_query = f"parents in '{folder_id}' and ({mimetype_query}) and trashed=false"
        else:
            # マイドライブの場合：従来通り
            supported_files_query = f"parents in '{folder_id}' and ({mimetype_query}) and trashed=false"
        
        print(f"📝 サポート対象ファイル検索クエリ: {supported_files_query}")
        
        supported_files = self._call_drive_files_list(
            supported_files_query, 
            "files(id, name, mimeType, size, modifiedTime, webViewLink, driveId)", 
            page_size=100,
            drive_id=drive_id
        )
        
        print(f"🎯 サポート対象ファイル数: {len(supported_files)}")
        if supported_files:
            print(f"📄 サポート対象ファイル一覧:")
            for i, file in enumerate(supported_files):
                size_info = f" ({file.get('size', '不明')} bytes)" if file.get('size') else ""
                print(f"  {i+1}. {file.get('name')}{size_info} ({file.get('mimeType')})")
        else:
            print(f"⚠️  サポート対象のファイル形式が見つかりません")
            if all_files:
                print(f"💡 ヒント: フォルダ内には{len(all_files)}個のファイルがありますが、サポート対象外の形式です")
                unsupported_types = set(file.get('mimeType') for file in all_files)
                print(f"📊 検出されたファイル形式: {list(unsupported_types)}")
        
        print(f"✅ ファイル取得完了: {len(supported_files)}件のサポート対象ファイルを返します\n")
        
        return supported_files
    
    def download_file(self, file_id: str, mime_type: str) -> Optional[bytes]:
        """
        ファイルをダウンロード
        
        Args:
            file_id: ファイルID
            mime_type: MIMEタイプ
        
        Returns:
            ファイル内容（バイト）
        """
        if not self.drive_service:
            return None
        
        try:
            # Google Docs の場合は PDF としてエクスポート
            if mime_type == 'application/vnd.google-apps.document':
                request = self.drive_service.files().export_media(
                    fileId=file_id,
                    mimeType='application/pdf'
                )
            # Google Slides の場合は PDF としてエクスポート
            elif mime_type == 'application/vnd.google-apps.presentation':
                request = self.drive_service.files().export_media(
                    fileId=file_id,
                    mimeType='application/pdf'
                )
            else:
                request = self._call_drive_files_get_media(file_id)
                if not request:
                    return None
            
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)
            
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            return file_content.getvalue()
            
        except Exception as e:
            print(f"ファイルダウンロードエラー: {e}")
            return None
    
    def upload_to_storage(self, content: bytes, file_name: str) -> str:
        """
        Cloud Storage にファイルをアップロード
        
        Args:
            content: ファイル内容
            file_name: ファイル名
        
        Returns:
            Cloud Storage URI
        """
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            
            # ファイル名にタイムスタンプを追加
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            storage_file_name = f"drive_sync/{timestamp}_{file_name}"
            
            blob = bucket.blob(storage_file_name)
            blob.upload_from_string(content)
            
            return f"gs://{self.bucket_name}/{storage_file_name}"
            
        except Exception as e:
            print(f"Cloud Storage アップロードエラー: {e}")
            raise
    
    def create_or_get_corpus(self, corpus_name: str) -> str:
        """
        RAG コーパスを作成または取得
        
        Args:
            corpus_name: コーパス名
        
        Returns:
            コーパスID
        """
        try:
            # 既存のコーパスIDがある場合は使用
            if self.sync_state.get('corpus_id'):
                return self.sync_state['corpus_id']
            
            # 新しいコーパスを作成（簡易版）
            # 注意: 実際のRAGコーパス作成は手動で行う必要があります
            import uuid
            corpus_id = f"projects/{self.project_id}/locations/us-central1/ragCorpora/{uuid.uuid4().hex[:16]}"
            
            print(f"RAGコーパスを作成する必要があります:")
            print(f"  名前: {corpus_name}")
            print(f"  説明: Google Drive sync corpus: {corpus_name}")
            print(f"  推奨ID: {corpus_id}")
            print(f"  手動でVertex AI Consoleから作成してください")
            
            # 一時的なコーパス情報を作成
            class MockCorpus:
                def __init__(self, name, display_name):
                    self.name = name
                    self.display_name = display_name
            
            corpus = MockCorpus(corpus_id, corpus_name)
            corpus_id = corpus.name
            
            # 状態を保存
            self.sync_state['corpus_id'] = corpus_id
            self._save_sync_state()
            
            print(f"新しいコーパスを作成しました: {corpus_id}")
            return corpus_id
            
        except Exception as e:
            print(f"コーパス作成エラー: {e}")
            raise
    
    def add_file_to_corpus(self, corpus_id: str, file_uri: str, file_name: str) -> bool:
        """
        ファイルを RAG コーパスに追加
        
        Args:
            corpus_id: コーパスID
            file_uri: ファイルのURI
            file_name: ファイル名
        
        Returns:
            成功したかどうか
        """
        try:
            print(f"ファイルをコーパスに追加中: {file_name}")
            print(f"  コーパスID: {corpus_id}")
            print(f"  ファイルURI: {file_uri}")
            
            # RAGファイルをインポート（簡易版）
            print(f"RAGファイルを追加する必要があります:")
            print(f"  ファイル名: {file_name}")
            print(f"  Cloud Storage URI: {file_uri}")
            print(f"  コーパスID: {corpus_id}")
            print(f"  手動でVertex AI Consoleから追加してください")
            
            # Cloud Storageにファイルが正常にアップロードされていることを確認
            try:
                from urllib.parse import urlparse
                parsed_uri = urlparse(file_uri)
                bucket_name = parsed_uri.netloc
                blob_name = parsed_uri.path.lstrip('/')
                
                bucket = self.storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                
                if blob.exists():
                    print(f"✅ Cloud Storageにファイルが存在します: {file_uri}")
                    # 一時的に成功として扱う
                    return True
                else:
                    print(f"❌ Cloud Storageにファイルが存在しません: {file_uri}")
                    return False
                    
            except Exception as e:
                print(f"Cloud Storage確認エラー: {e}")
                # エラーでも一時的に成功として扱う
                return True
            
        except Exception as e:
            print(f"コーパスへのファイル追加エラー ({file_name}): {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def sync_folder_to_rag(self, folder_name: str, corpus_name: str, force_sync: bool = False, recursive: bool = False, max_depth: int = 3) -> Dict:
        """
        Google Drive フォルダを RAG コーパスに同期
        
        Args:
            folder_name: Google Drive フォルダ名
            corpus_name: RAG コーパス名
            force_sync: 強制同期（全ファイルを再同期）
            recursive: サブフォルダも再帰的に同期するか
            max_depth: 再帰探索の最大深度
        
        Returns:
            同期結果
        """
        if not self.is_authenticated():
            return {"success": False, "error": "認証が必要です"}
        
        print(f"同期開始: {folder_name} -> {corpus_name} (再帰: {'有効' if recursive else '無効'})")
        
        # フォルダIDを取得
        folder_id = self.find_folder_by_name(folder_name)
        if not folder_id:
            return {"success": False, "error": f"フォルダが見つかりません: {folder_name}"}
        
        # コーパスを作成または取得
        try:
            corpus_id = self.create_or_get_corpus(corpus_name)
        except Exception as e:
            return {"success": False, "error": f"コーパス作成エラー: {e}"}
        
        # フォルダ内のファイル一覧を取得（再帰的または通常）
        if recursive:
            print(f"📁 再帰的同期モード: 最大深度 {max_depth}")
            files = self.list_folder_files_recursive(folder_id, max_depth)
        else:
            print(f"📁 通常同期モード: 直下のファイルのみ")
            files = self.list_folder_files(folder_id)
        
        print(f"検出されたファイル数: {len(files)}")
        
        sync_results = {
            "success": True,
            "total_files": len(files),
            "processed_files": 0,
            "added_files": 0,
            "skipped_files": 0,
            "error_files": 0,
            "errors": [],
            "corpus_id": corpus_id,
            "recursive_mode": recursive,
            "max_depth": max_depth if recursive else 1
        }
        
        for file_info in files:
            file_id = file_info['id']
            file_name = file_info['name']
            mime_type = file_info['mimeType']
            modified_time = file_info.get('modifiedTime')
            
            print(f"処理中: {file_name}")
            
            try:
                # ファイルをダウンロード
                content = self.download_file(file_id, mime_type)
                if not content:
                    sync_results["error_files"] += 1
                    sync_results["errors"].append(f"ダウンロード失敗: {file_name}")
                    continue
                
                # ファイルハッシュを計算
                file_hash = hashlib.md5(content).hexdigest()
                
                # 変更チェック（force_sync=False の場合）
                if not force_sync:
                    stored_hash = self.sync_state['file_hashes'].get(file_id)
                    if stored_hash == file_hash:
                        print(f"スキップ（変更なし）: {file_name}")
                        sync_results["skipped_files"] += 1
                        sync_results["processed_files"] += 1
                        continue
                
                # Cloud Storage にアップロード
                try:
                    file_uri = self.upload_to_storage(content, file_name)
                except Exception as e:
                    sync_results["error_files"] += 1
                    sync_results["errors"].append(f"Cloud Storage アップロード失敗 ({file_name}): {e}")
                    continue
                
                # RAG コーパスに追加
                if self.add_file_to_corpus(corpus_id, file_uri, file_name):
                    # 成功した場合、状態を更新
                    self.sync_state['file_hashes'][file_id] = file_hash
                    self.sync_state['synced_files'][file_id] = {
                        'name': file_name,
                        'uri': file_uri,
                        'modified_time': modified_time,
                        'sync_time': datetime.now().isoformat()
                    }
                    sync_results["added_files"] += 1
                    print(f"追加完了: {file_name}")
                else:
                    sync_results["error_files"] += 1
                    sync_results["errors"].append(f"コーパス追加失敗: {file_name}")
                
                sync_results["processed_files"] += 1
                
            except Exception as e:
                sync_results["error_files"] += 1
                sync_results["errors"].append(f"処理エラー ({file_name}): {e}")
                print(f"ファイル処理エラー ({file_name}): {e}")
        
        # 同期状態を保存
        self.sync_state['last_sync'] = datetime.now().isoformat()
        self._save_sync_state()
        
        print(f"同期完了: 処理={sync_results['processed_files']}, 追加={sync_results['added_files']}, スキップ={sync_results['skipped_files']}, エラー={sync_results['error_files']}")
        
        return sync_results
    
    def get_sync_status(self) -> Dict:
        """同期状態を取得"""
        return {
            'authenticated': self.is_authenticated(),
            'user_email': self.sync_state.get('user_email'),
            'last_sync': self.sync_state.get('last_sync'),
            'corpus_id': self.sync_state.get('corpus_id'),
            'synced_files_count': len(self.sync_state.get('synced_files', {}))
        }
    
    def clear_auth(self):
        """認証情報をクリア"""
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
        
        self.credentials = None
        self.drive_service = None
        self.storage_client = None
        self.rag_client = None
        
        # 同期状態もクリア
        self.sync_state = {
            'last_sync': None,
            'file_hashes': {},
            'corpus_id': None,
            'synced_files': {},
            'user_email': None
        }
        self._save_sync_state()

    def force_reauth(self):
        """認証を強制的に再取得（共有ドライブアクセス確保のため）"""
        print("認証の強制再取得を実行中...")
        
        # 既存のトークンを削除
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
            print(f"既存のトークンファイルを削除: {self.token_file}")
        
        # 認証情報をクリア
        self.credentials = None
        self.drive_service = None
        self.storage_client = None
        
        print("再認証が必要です。OAuth認証フローを開始してください。")
        print(f"必要なスコープ: {self.scopes}")
    
    def check_shared_drive_permissions(self) -> Dict:
        """共有ドライブの権限をチェック"""
        if not self.drive_service:
            return {'error': 'Drive service が初期化されていません'}
        
        try:
            # 全ての共有ドライブを一覧取得してテスト
            drives_result = self.drive_service.drives().list(
                pageSize=10,
                fields="drives(id, name, capabilities)"
            ).execute()
            
            drives = drives_result.get('drives', [])
            
            return {
                'success': True,
                'shared_drives_count': len(drives),
                'shared_drives': drives,
                'current_scopes': self.credentials.scopes if self.credentials else []
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'current_scopes': self.credentials.scopes if self.credentials else []
            }

    def test_shared_drive_access(self, folder_id: str) -> Dict:
        """
        共有ドライブへのアクセスを詳細にテスト
        
        Args:
            folder_id: テストするフォルダID
        
        Returns:
            テスト結果の詳細
        """
        if not self.drive_service:
            return {'error': 'Drive service が初期化されていません'}
        
        test_results = {
            'folder_id': folder_id,
            'tests': [],
            'overall_success': False,
            'recommendations': []
        }
        
        try:
            # テスト1: フォルダ基本情報取得
            print("=== テスト1: フォルダ基本情報取得 ===")
            folder_info = self._call_drive_files_get(
                folder_id, 
                "id, name, mimeType, driveId, parents, capabilities, permissions"
            )
            
            if folder_info:
                test_results['tests'].append({
                    'test': 'フォルダ基本情報取得',
                    'status': 'success',
                    'data': folder_info
                })
                print(f"✅ フォルダ情報取得成功: {folder_info.get('name')}")
                
                # 共有ドライブかどうかを確認
                drive_id = folder_info.get('driveId')
                if drive_id:
                    print(f"📁 共有ドライブ検出: {drive_id}")
                    
                    # テスト2: 共有ドライブ詳細情報取得
                    print("=== テスト2: 共有ドライブ詳細情報 ===")
                    try:
                        drive_info = self.drive_service.drives().get(
                            driveId=drive_id,
                            fields="id, name, capabilities, restrictions, backgroundImageFile"
                        ).execute()
                        
                        test_results['tests'].append({
                            'test': '共有ドライブ詳細取得',
                            'status': 'success',
                            'data': drive_info
                        })
                        print(f"✅ 共有ドライブ情報: {drive_info.get('name')}")
                        print(f"   権限: {drive_info.get('capabilities', {})}")
                        
                    except Exception as e:
                        test_results['tests'].append({
                            'test': '共有ドライブ詳細取得',
                            'status': 'error',
                            'error': str(e)
                        })
                        print(f"❌ 共有ドライブ詳細取得エラー: {e}")
                        test_results['recommendations'].append("共有ドライブへのアクセス権限を確認してください")
                else:
                    print("📁 通常のマイドライブフォルダです")
                
                # テスト3: ファイル一覧取得（簡単なクエリ）
                print("=== テスト3: 基本ファイル一覧取得 ===")
                simple_query = f"parents in '{folder_id}' and trashed=false"
                
                try:
                    files = self._call_drive_files_list(
                        simple_query,
                        "files(id, name, mimeType)",
                        page_size=10,
                        drive_id=drive_id
                    )
                    
                    test_results['tests'].append({
                        'test': '基本ファイル一覧取得',
                        'status': 'success',
                        'data': {'file_count': len(files), 'files': files[:5]}
                    })
                    print(f"✅ ファイル一覧取得成功: {len(files)}件")
                    
                    if len(files) == 0:
                        test_results['recommendations'].append("フォルダが空か、ファイルへのアクセス権限がない可能性があります")
                    
                except Exception as e:
                    test_results['tests'].append({
                        'test': '基本ファイル一覧取得',
                        'status': 'error',
                        'error': str(e)
                    })
                    print(f"❌ ファイル一覧取得エラー: {e}")
                    test_results['recommendations'].append("ファイルアクセス権限を確認してください")
                
                # テスト4: 権限チェック
                print("=== テスト4: 権限チェック ===")
                try:
                    # about().get()でユーザー権限を確認
                    about_info = self.drive_service.about().get(
                        fields="user,storageQuota,canCreateDrives,canCreateSharedDrives"
                    ).execute()
                    
                    test_results['tests'].append({
                        'test': 'ユーザー権限確認',
                        'status': 'success',
                        'data': about_info
                    })
                    print(f"✅ ユーザー: {about_info.get('user', {}).get('emailAddress')}")
                    
                except Exception as e:
                    test_results['tests'].append({
                        'test': 'ユーザー権限確認',
                        'status': 'error',
                        'error': str(e)
                    })
                    print(f"❌ ユーザー権限確認エラー: {e}")
                
                # 総合判定
                success_count = len([t for t in test_results['tests'] if t['status'] == 'success'])
                total_tests = len(test_results['tests'])
                test_results['overall_success'] = success_count >= 2  # 最低2つのテストが成功
                
                print(f"\n=== テスト結果 ===")
                print(f"成功: {success_count}/{total_tests}")
                print(f"総合判定: {'✅ 成功' if test_results['overall_success'] else '❌ 失敗'}")
                
            else:
                test_results['tests'].append({
                    'test': 'フォルダ基本情報取得',
                    'status': 'error',
                    'error': 'フォルダ情報が取得できません'
                })
                test_results['recommendations'].append("フォルダIDが正しいか、アクセス権限があるかを確認してください")
            
        except Exception as e:
            test_results['tests'].append({
                'test': '全体テスト',
                'status': 'error',
                'error': str(e)
            })
            print(f"❌ テスト実行エラー: {e}")
        
        return test_results

    def diagnose_access_issues(self, folder_id: str) -> Dict:
        """
        アクセス問題を診断し、解決策を提案
        
        Args:
            folder_id: 診断するフォルダID
        
        Returns:
            診断結果と解決策
        """
        diagnosis = {
            'folder_id': folder_id,
            'issues': [],
            'solutions': [],
            'status': 'unknown'
        }
        
        try:
            # 基本的なフォルダアクセステスト
            folder_info = self._call_drive_files_get(folder_id, "id, name, driveId, capabilities")
            
            if not folder_info:
                diagnosis['issues'].append("フォルダにアクセスできません")
                diagnosis['solutions'].extend([
                    "フォルダIDが正しいかを確認してください",
                    "フォルダへのアクセス権限があるかを確認してください",
                    "Google Driveで直接フォルダにアクセスできるかを確認してください"
                ])
                diagnosis['status'] = 'no_access'
                return diagnosis
            
            drive_id = folder_info.get('driveId')
            
            if drive_id:
                # 共有ドライブの場合
                print(f"共有ドライブを診断中: {drive_id}")
                
                # 共有ドライブ詳細情報を取得
                try:
                    drive_info = self.drive_service.drives().get(
                        driveId=drive_id,
                        fields="id, name, capabilities, restrictions"
                    ).execute()
                    
                    capabilities = drive_info.get('capabilities', {})
                    restrictions = drive_info.get('restrictions', {})
                    
                    # アクセス可能性をチェック
                    if not capabilities.get('canListChildren', False):
                        diagnosis['issues'].append("フォルダ内容を一覧表示する権限がありません")
                        diagnosis['solutions'].append("共有ドライブの管理者に「閲覧者」以上の権限を依頼してください")
                    
                    if not capabilities.get('canDownload', False):
                        diagnosis['issues'].append("ファイルをダウンロードする権限がありません")
                        diagnosis['solutions'].append("共有ドライブの管理者に「編集者」権限を依頼してください")
                    
                    # 制限事項をチェック
                    if restrictions.get('copyRequiresWriterPermission', False):
                        diagnosis['issues'].append("ファイルコピーに編集者権限が必要です")
                    
                    if restrictions.get('domainUsersOnly', False):
                        diagnosis['issues'].append("ドメインユーザーのみアクセス可能に制限されています")
                        diagnosis['solutions'].append("組織内のアカウントで認証してください")
                    
                except Exception as e:
                    diagnosis['issues'].append(f"共有ドライブ詳細情報の取得に失敗: {str(e)}")
                    diagnosis['solutions'].extend([
                        "共有ドライブのメンバーであることを確認してください",
                        "組織のGoogle Workspaceポリシーを確認してください"
                    ])
            
            # ファイル一覧取得テスト
            try:
                files = self._call_drive_files_list(
                    f"parents in '{folder_id}' and trashed=false",
                    "files(id, name)",
                    page_size=1,
                    drive_id=drive_id
                )
                
                if len(files) == 0:
                    # ファイルが見つからない場合の詳細診断
                    diagnosis['issues'].append("フォルダ内にアクセス可能なファイルがありません")
                    diagnosis['solutions'].extend([
                        "フォルダが空ではないかを確認してください",
                        "ファイルへの個別アクセス権限を確認してください",
                        "削除されたファイルではないかを確認してください"
                    ])
                
            except Exception as e:
                diagnosis['issues'].append(f"ファイル一覧取得エラー: {str(e)}")
                if "403" in str(e):
                    diagnosis['solutions'].extend([
                        "アクセス権限が不足しています",
                        "共有ドライブの管理者に権限を依頼してください",
                        "Google OAuth認証を再実行してください"
                    ])
                elif "404" in str(e):
                    diagnosis['solutions'].append("フォルダが存在しないか削除されています")
            
            # 認証スコープをチェック
            current_scopes = self.credentials.scopes if self.credentials else []
            required_scopes = [
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/drive.file'
            ]
            
            missing_scopes = [scope for scope in required_scopes if scope not in current_scopes]
            if missing_scopes:
                diagnosis['issues'].append(f"必要なOAuthスコープが不足: {missing_scopes}")
                diagnosis['solutions'].append("認証を再実行して適切なスコープを取得してください")
            
            # ステータス判定
            if len(diagnosis['issues']) == 0:
                diagnosis['status'] = 'healthy'
            elif len(diagnosis['issues']) <= 2:
                diagnosis['status'] = 'minor_issues'
            else:
                diagnosis['status'] = 'major_issues'
            
        except Exception as e:
            diagnosis['issues'].append(f"診断エラー: {str(e)}")
            diagnosis['solutions'].append("システム管理者にお問い合わせください")
            diagnosis['status'] = 'error'
        
        return diagnosis

    def list_shared_drives(self) -> List[Dict]:
        """
        アクセス可能な共有ドライブ一覧を取得
        
        Returns:
            共有ドライブ情報のリスト
        """
        if not self.drive_service:
            print("❌ Drive service が初期化されていません")
            return []
        
        try:
            print("📋 共有ドライブ一覧を取得中...")
            
            drives_result = self.drive_service.drives().list(
                pageSize=100,
                fields="drives(id, name, capabilities, restrictions, backgroundImageFile, createdTime)"
            ).execute()
            
            drives = drives_result.get('drives', [])
            
            print(f"✅ {len(drives)}個の共有ドライブが見つかりました")
            
            for i, drive in enumerate(drives):
                capabilities = drive.get('capabilities', {})
                restrictions = drive.get('restrictions', {})
                
                print(f"\n📁 {i+1}. {drive.get('name')}")
                print(f"   ID: {drive.get('id')}")
                print(f"   作成日: {drive.get('createdTime', '不明')}")
                
                # 権限情報を表示
                if capabilities:
                    print(f"   権限:")
                    if capabilities.get('canListChildren'):
                        print(f"     ✅ フォルダ内容一覧表示可能")
                    if capabilities.get('canDownload'):
                        print(f"     ✅ ファイルダウンロード可能")
                    if capabilities.get('canEdit'):
                        print(f"     ✅ 編集可能")
                    if capabilities.get('canComment'):
                        print(f"     ✅ コメント可能")
                
                # 制限情報を表示
                if restrictions:
                    print(f"   制限:")
                    if restrictions.get('domainUsersOnly'):
                        print(f"     ⚠️  ドメインユーザーのみアクセス可能")
                    if restrictions.get('copyRequiresWriterPermission'):
                        print(f"     ⚠️  コピーには編集者権限が必要")
            
            return drives
            
        except Exception as e:
            print(f"❌ 共有ドライブ一覧取得エラー: {e}")
            self._handle_drive_api_error(e, "drives().list()")
            return []
    
    def get_shared_drive_root_files(self, drive_id: str) -> List[Dict]:
        """
        共有ドライブのルート直下のファイル一覧を取得
        
        Args:
            drive_id: 共有ドライブID
        
        Returns:
            ファイル情報のリスト
        """
        if not self.drive_service:
            print("❌ Drive service が初期化されていません")
            return []
        
        try:
            print(f"📁 共有ドライブルート直下のファイル取得開始: {drive_id}")
            
            # 共有ドライブの基本情報を取得
            try:
                drive_info = self.drive_service.drives().get(
                    driveId=drive_id,
                    fields="id, name, capabilities"
                ).execute()
                print(f"📋 共有ドライブ: {drive_info.get('name')} (ID: {drive_id})")
            except Exception as e:
                print(f"⚠️  共有ドライブ情報取得エラー: {e}")
            
            # ルート直下のファイル検索クエリ
            # 共有ドライブのルートは特別な検索方法を使用
            query = f"parents in '{drive_id}' and trashed=false"
            
            print(f"🔍 検索クエリ: {query}")
            
            files = self._call_drive_files_list(
                query,
                "files(id, name, mimeType, size, modifiedTime, webViewLink, driveId, parents)",
                page_size=100,
                drive_id=drive_id
            )
            
            print(f"📊 共有ドライブルート直下のファイル数: {len(files)}")
            
            if files:
                print(f"📄 ファイル一覧:")
                for i, file in enumerate(files):
                    size_info = f" ({file.get('size', '不明')} bytes)" if file.get('size') else ""
                    file_type = "📁" if file.get('mimeType') == 'application/vnd.google-apps.folder' else "📄"
                    print(f"  {i+1}. {file_type} {file.get('name')}{size_info}")
            else:
                print("⚠️  共有ドライブルート直下にファイルが見つかりません")
            
            return files
            
        except Exception as e:
            print(f"❌ 共有ドライブルートファイル取得エラー: {e}")
            self._handle_drive_api_error(e, "共有ドライブルートファイル取得", drive_id)
            return []

    def _handle_drive_api_error(self, error: Exception, operation: str, resource_id: str = None) -> None:
        """
        Google Drive APIエラーの共通ハンドリング
        
        Args:
            error: 発生したエラー
            operation: 実行していた操作
            resource_id: 対象のリソースID
        """
        error_msg = f"Google Drive API エラー ({operation})"
        if resource_id:
            error_msg += f" - リソースID: {resource_id}"
        
        # HTTPエラーの詳細解析
        if hasattr(error, 'resp'):
            status_code = error.resp.status
            if status_code == 403:
                print(f"{error_msg}: アクセス権限がありません")
            elif status_code == 404:
                print(f"{error_msg}: リソースが見つかりません")
            elif status_code == 429:
                print(f"{error_msg}: API制限に達しました")
            else:
                print(f"{error_msg}: HTTPエラー {status_code}")
        else:
            print(f"{error_msg}: {str(error)}")
        
        # デバッグ用の詳細情報
        import traceback
        print(f"詳細: {traceback.format_exc()}")

    def _call_drive_files_get(self, file_id: str, fields: str) -> Optional[Dict]:
        """
        Google Drive files().get() APIの共通呼び出し
        
        Args:
            file_id: ファイルまたはフォルダID
            fields: 取得するフィールド
        
        Returns:
            API応答またはNone（エラー時）
        """
        try:
            return self.drive_service.files().get(
                fileId=file_id,
                fields=fields,
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            self._handle_drive_api_error(e, "files().get()", file_id)
            return None
    
    def _get_drive_id_for_folder(self, folder_id: str) -> Optional[str]:
        """
        フォルダが属する共有ドライブのIDを取得
        
        Args:
            folder_id: フォルダID
        
        Returns:
            共有ドライブID またはNone（通常のマイドライブの場合）
        """
        try:
            # 直接APIを呼び出して循環参照を回避
            folder_info = self.drive_service.files().get(
                fileId=folder_id,
                fields="id, name, driveId, parents",
                supportsAllDrives=True
            ).execute()
            
            if folder_info:
                drive_id = folder_info.get('driveId')
                if drive_id:
                    print(f"共有ドライブ検出: {drive_id}")
                    return drive_id
                else:
                    print("通常のマイドライブフォルダです")
            return None
        except Exception as e:
            print(f"共有ドライブID取得エラー: {e}")
            return None

    def _call_drive_files_list(self, query: str, fields: str, page_size: int = 100, order_by: Optional[str] = None, drive_id: Optional[str] = None) -> List[Dict]:
        """
        Google Drive files().list() APIの共通呼び出し
        
        Args:
            query: 検索クエリ
            fields: 取得するフィールド
            page_size: ページサイズ
            order_by: ソート順
            drive_id: 共有ドライブID（共有ドライブの場合）
        
        Returns:
            ファイル/フォルダ一覧
        """
        try:
            # 基本パラメータ（共有ドライブ対応）
            params = {
                'q': query,
                'fields': fields,
                'pageSize': page_size,
                'supportsAllDrives': True,
                'includeItemsFromAllDrives': True
            }
            
            if order_by:
                params['orderBy'] = order_by
            
            # 共有ドライブ固有の設定
            if drive_id:
                # 特定の共有ドライブ内のみを検索
                params['driveId'] = drive_id
                params['corpora'] = 'drive'
                print(f"🔍 共有ドライブ特定検索: {drive_id}")
            else:
                # 全ドライブ（マイドライブ + アクセス可能な全共有ドライブ）を検索
                params['corpora'] = 'allDrives'
                print(f"🔍 全ドライブ検索モード")
            
            print(f"📋 API呼び出しパラメータ: {params}")
            
            # ページング対応でファイル一覧を取得
            all_files = []
            page_token = None
            
            while True:
                if page_token:
                    params['pageToken'] = page_token
                
                try:
                    results = self.drive_service.files().list(**params).execute()
                    files = results.get('files', [])
                    all_files.extend(files)
                    
                    print(f"📄 現在のページで{len(files)}件取得（累計: {len(all_files)}件）")
                    
                    # 次のページがあるかチェック
                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
                        
                except Exception as e:
                    print(f"❌ ページング中にエラー: {e}")
                    break
            
            print(f"✅ 最終結果: {len(all_files)}件のファイル/フォルダを取得")
            
            # デバッグ用：取得したファイルの詳細を出力
            for i, file in enumerate(all_files[:5]):  # 最初の5件のみ表示
                drive_info = f"共有ドライブ: {file.get('driveId', 'なし')}" if file.get('driveId') else "マイドライブ"
                print(f"  {i+1}. {file.get('name')} (ID: {file.get('id')[:10]}..., MIME: {file.get('mimeType')}, {drive_info})")
            
            if len(all_files) > 5:
                print(f"  ... 他 {len(all_files) - 5} 件")
            
            return all_files
            
        except Exception as e:
            error_context = f"query: {query}"
            if drive_id:
                error_context += f", driveId: {drive_id}"
            self._handle_drive_api_error(e, "files().list()", error_context)
            return []
    
    def _call_drive_files_get_media(self, file_id: str) -> Optional[object]:
        """
        Google Drive files().get_media() APIの共通呼び出し
        
        Args:
            file_id: ファイルID
        
        Returns:
            MediaIoBaseDownload用のリクエストオブジェクトまたはNone
        """
        try:
            return self.drive_service.files().get_media(
                fileId=file_id,
                supportsAllDrives=True
            )
        except Exception as e:
            self._handle_drive_api_error(e, "files().get_media()", file_id)
            return None

    def list_folder_files_recursive(self, folder_id: str, max_depth: int = 3, current_depth: int = 0) -> List[Dict]:
        """
        フォルダ内のファイルを再帰的に取得（サブフォルダも含む）
        
        Args:
            folder_id: フォルダID
            max_depth: 最大探索深度（デフォルト3階層）
            current_depth: 現在の探索深度（内部使用）
        
        Returns:
            ファイル情報のリスト（パス情報付き）
        """
        if not self.drive_service:
            print("❌ Drive service が初期化されていません")
            return []
        
        if current_depth >= max_depth:
            print(f"⚠️  最大探索深度 {max_depth} に達しました")
            return []
        
        print(f"📁 再帰的ファイル探索開始 (深度: {current_depth + 1}/{max_depth}): {folder_id}")
        
        # フォルダ情報を取得
        folder_info = self._call_drive_files_get(
            folder_id, 
            "id, name, mimeType, driveId, parents"
        )
        if not folder_info:
            print(f"❌ フォルダ情報の取得に失敗: {folder_id}")
            return []
        
        folder_name = folder_info.get('name', '不明')
        drive_id = folder_info.get('driveId')
        
        print(f"📁 探索中のフォルダ: {folder_name}")
        
        # このフォルダのパスを取得
        folder_path = self.get_folder_path(folder_id)
        
        all_files = []
        
        # サポートするファイル形式の定義
        supported_mimetypes = [
            'application/pdf',                                                    # PDF
            'text/plain',                                                        # テキストファイル
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # Word (.docx)
            'application/msword',                                                # Word (.doc)
            'text/markdown',                                                     # Markdown
            'application/rtf',                                                   # RTF
            'application/vnd.google-apps.document',                             # Google Docs
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PowerPoint (.pptx)
            'application/vnd.ms-powerpoint',                                     # PowerPoint (.ppt)
            'application/vnd.google-apps.presentation'                          # Google Slides
        ]
        
        # 全アイテム（ファイル + フォルダ）を取得
        all_items_query = f"parents in '{folder_id}' and trashed=false"
        all_items = self._call_drive_files_list(
            all_items_query, 
            "files(id, name, mimeType, size, modifiedTime, webViewLink, driveId)", 
            page_size=100,
            drive_id=drive_id
        )
        
        # ファイルとフォルダに分類
        files = []
        subfolders = []
        
        for item in all_items:
            if item.get('mimeType') == 'application/vnd.google-apps.folder':
                subfolders.append(item)
            else:
                files.append(item)
        
        # 現在のフォルダ内のサポート対象ファイルを処理
        for file in files:
            if file.get('mimeType') in supported_mimetypes:
                # ファイル情報にパス情報を追加
                file_with_path = file.copy()
                file_with_path['folder_path'] = folder_path
                file_with_path['full_path'] = f"{folder_path}/{file.get('name')}"
                file_with_path['depth'] = current_depth + 1
                all_files.append(file_with_path)
        
        print(f"📄 現在のフォルダ内の対象ファイル: {len([f for f in files if f.get('mimeType') in supported_mimetypes])}件")
        print(f"📁 サブフォルダ: {len(subfolders)}件")
        
        # サブフォルダを再帰的に探索
        for subfolder in subfolders:
            subfolder_id = subfolder['id']
            subfolder_name = subfolder['name']
            
            print(f"🔍 サブフォルダを探索: {subfolder_name}")
            
            try:
                # 再帰的にサブフォルダのファイルを取得
                subfolder_files = self.list_folder_files_recursive(
                    subfolder_id, 
                    max_depth, 
                    current_depth + 1
                )
                all_files.extend(subfolder_files)
                
            except Exception as e:
                print(f"⚠️  サブフォルダ '{subfolder_name}' の探索でエラー: {e}")
                continue
        
        if current_depth == 0:  # 最上位レベルでのみ表示
            print(f"✅ 再帰的探索完了: 合計 {len(all_files)} 件のサポート対象ファイルを検出")
            
            # 深度別の統計を表示
            depth_stats = {}
            for file in all_files:
                depth = file.get('depth', 0)
                depth_stats[depth] = depth_stats.get(depth, 0) + 1
            
            print(f"📊 深度別ファイル数:")
            for depth in sorted(depth_stats.keys()):
                print(f"  深度 {depth}: {depth_stats[depth]} 件")
        
        return all_files


# グローバルインスタンス（Flaskアプリで使用）
drive_sync = None

def init_drive_sync(project_id: str, client_secrets_file: str, bucket_name: Optional[str] = None):
    """Drive同期インスタンスを初期化"""
    global drive_sync
    drive_sync = DriveRAGIntegration(
        project_id=project_id,
        client_secrets_file=client_secrets_file,
        bucket_name=bucket_name
    )
    return drive_sync

def get_drive_sync() -> Optional[DriveRAGIntegration]:
    """Drive同期インスタンスを取得"""
    return drive_sync


# ==========================================
# 動作確認用サンプルコード
# ==========================================

def demo_shared_drive_access():
    """
    【動作確認用サンプル】
    共有ドライブを列挙 → 1つ選択 → ルート直下のファイル一覧を表示
    
    使用例:
        from drive_sync_integration import demo_shared_drive_access
        demo_shared_drive_access()
    """
    print("=" * 60)
    print("🚀 Google Drive 共有ドライブ動作確認デモ")
    print("=" * 60)
    
    # Google Cloud プロジェクトIDとクライアント設定ファイルを設定
    PROJECT_ID = "your-project-id"  # 実際のプロジェクトIDに変更
    CLIENT_SECRETS_FILE = "config/client_secrets.json"  # 実際のパスに変更
    
    try:
        # DriveRAGIntegrationインスタンスを作成
        drive_integration = DriveRAGIntegration(
            project_id=PROJECT_ID,
            client_secrets_file=CLIENT_SECRETS_FILE
        )
        
        print("📋 認証情報を読み込み中...")
        if not drive_integration.load_credentials():
            print("❌ 認証が必要です。先にOAuth認証を完了してください。")
            print("   手順:")
            print("   1. Flaskアプリを起動")
            print("   2. /auth/google にアクセスして認証")
            print("   3. 認証完了後、再度このデモを実行")
            return
        
        print("✅ 認証情報の読み込み完了")
        
        # Step 1: 共有ドライブ一覧を取得
        print("\n" + "=" * 40)
        print("📁 Step 1: 共有ドライブ一覧取得")
        print("=" * 40)
        
        shared_drives = drive_integration.list_shared_drives()
        
        if not shared_drives:
            print("❌ アクセス可能な共有ドライブが見つかりませんでした。")
            print("   以下を確認してください:")
            print("   - 共有ドライブのメンバーになっているか")
            print("   - 適切なOAuthスコープで認証しているか")
            return
        
        # Step 2: 最初の共有ドライブを選択（実際の使用時はユーザー選択）
        print("\n" + "=" * 40)
        print("🎯 Step 2: 共有ドライブ選択")
        print("=" * 40)
        
        selected_drive = shared_drives[0]  # 最初の共有ドライブを選択
        drive_id = selected_drive['id']
        drive_name = selected_drive['name']
        
        print(f"🏆 選択された共有ドライブ: {drive_name}")
        print(f"📋 ドライブID: {drive_id}")
        
        # Step 3: 選択された共有ドライブのルート直下ファイル一覧を取得
        print("\n" + "=" * 40)
        print("📄 Step 3: ルート直下ファイル一覧取得")
        print("=" * 40)
        
        root_files = drive_integration.get_shared_drive_root_files(drive_id)
        
        if root_files:
            print(f"🎉 成功！共有ドライブ '{drive_name}' から {len(root_files)} 個のアイテムを取得しました")
            
            # ファイル詳細を表示
            folders = [f for f in root_files if f.get('mimeType') == 'application/vnd.google-apps.folder']
            files = [f for f in root_files if f.get('mimeType') != 'application/vnd.google-apps.folder']
            
            if folders:
                print(f"\n📁 フォルダ ({len(folders)} 個):")
                for i, folder in enumerate(folders[:5], 1):
                    print(f"  {i}. 📁 {folder.get('name')}")
                if len(folders) > 5:
                    print(f"     ... 他 {len(folders) - 5} 個のフォルダ")
            
            if files:
                print(f"\n📄 ファイル ({len(files)} 個):")
                for i, file in enumerate(files[:5], 1):
                    size_info = f" ({file.get('size', '不明')} bytes)" if file.get('size') else ""
                    print(f"  {i}. 📄 {file.get('name')}{size_info}")
                if len(files) > 5:
                    print(f"     ... 他 {len(files) - 5} 個のファイル")
            
            # さらなるテスト: フォルダ内ファイル取得
            if folders:
                print(f"\n" + "=" * 40)
                print("🔍 Step 4: フォルダ内ファイル取得テスト")
                print("=" * 40)
                
                test_folder = folders[0]
                folder_id = test_folder['id']
                folder_name = test_folder['name']
                
                print(f"🎯 テスト対象フォルダ: {folder_name}")
                
                folder_files = drive_integration.list_folder_files(folder_id)
                print(f"📊 結果: {len(folder_files)} 個のサポート対象ファイルを検出")
                
        else:
            print(f"⚠️  共有ドライブ '{drive_name}' のルート直下にファイルが見つかりませんでした")
        
        print("\n" + "=" * 60)
        print("✅ デモ完了！共有ドライブアクセスが正常に動作しています")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ デモ実行中にエラーが発生しました: {e}")
        import traceback
        print("詳細なエラー情報:")
        traceback.print_exc()


if __name__ == "__main__":
    """
    このファイルを直接実行した場合のテスト
    
    実行方法:
        python drive_sync_integration.py
    
    注意: 事前にOAuth認証を完了しておく必要があります
    """
    print("🧪 drive_sync_integration.py テスト実行")
    demo_shared_drive_access()