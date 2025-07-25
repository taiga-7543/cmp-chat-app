from flask import Flask, request, jsonify, render_template, Response
from flask_httpauth import HTTPBasicAuth
from google import genai
from google.genai import types
import json
import os
import re
from datetime import datetime
import hashlib
import base64
import gc
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

app = Flask(__name__)
auth = HTTPBasicAuth()

# 環境変数から設定を読み込み
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT', 'dotd-development-division')
RAG_CORPUS = os.environ.get('RAG_CORPUS', f'projects/{PROJECT_ID}/locations/us-central1/ragCorpora/5188146770730811392')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

# 認証設定
AUTH_USERNAME = os.environ.get('AUTH_USERNAME', 'u7F3kL9pQ2zX')
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', 's8Vn2BqT5wXc')

# RAGシステム共通設定
RAG_SYSTEM_PROMPT = """あなたはRAG（Retrieval-Augmented Generation）システムです。以下のルールに厳密に従って回答してください：

1. **RAG検索結果のみを使用**: 提供された検索結果（retrieved content）の情報のみを使用して回答してください
2. **一般知識の禁止**: あなたの事前学習データや一般的な知識は一切使用しないでください
3. **情報がない場合**: RAG検索結果に関連情報がない場合は「提供された資料には該当する情報が見つかりませんでした」と回答してください
4. **引用の明確化**: 回答には必ずRAG検索結果から取得した情報であることを明示してください
5. **推測の禁止**: 検索結果にない情報については推測や補完を行わないでください
6. **完全な依存**: 回答の根拠は100%検索結果に基づいている必要があります

これらのルールを絶対に守って、以下の質問に回答してください。"""

# デフォルト質問リスト生成
def generate_default_questions(user_message):
    """デフォルトの関連質問リストを生成"""
    return [
        f"{user_message}の基本的な定義とは何ですか？",
        f"{user_message}の具体的な事例を教えてください",
        f"{user_message}のメリットとデメリットは何ですか？",
        f"{user_message}の最新の動向はどうですか？",
        f"{user_message}に関連する技術や手法はありますか？"
    ]

# 共通設定作成関数
def create_rag_tools():
    """RAGツール設定を作成"""
    return [
        types.Tool(
            retrieval=types.Retrieval(
                vertex_rag_store=types.VertexRagStore(
                    rag_resources=[
                        types.VertexRagStoreRagResource(
                            rag_corpus=RAG_CORPUS
                        )
                    ],
                )
            )
        )
    ]

def create_safety_settings():
    """セーフティ設定を作成"""
    return [
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF")
    ]

def create_generate_config(temperature=0.8, top_p=0.9, max_tokens=65536, include_tools=True, include_thinking=False, seed=None):
    """GenerateContentConfigを作成"""
    config_params = {
        'temperature': temperature,
        'top_p': top_p,
        'max_output_tokens': max_tokens,
        'safety_settings': create_safety_settings(),
    }
    
    if seed is not None:
        config_params['seed'] = seed
    
    if include_tools:
        config_params['tools'] = create_rag_tools()
    
    if include_thinking:
        # ThinkingConfigが利用可能な場合のみ追加
        try:
            thinking_config_available = False
            if hasattr(types, 'ThinkingConfig'):
                test_config = types.ThinkingConfig(thinking_budget=-1)
                thinking_config_available = True
            else:
                from google.genai.types import ThinkingConfig
                test_config = ThinkingConfig(thinking_budget=-1)
                thinking_config_available = True
            
            if thinking_config_available:
                config_params['thinking_config'] = types.ThinkingConfig(thinking_budget=-1)
        except (AttributeError, TypeError, ValueError, ImportError):
            pass  # ThinkingConfigが利用できない場合は無視
    
    # 安全にGenerateContentConfigを作成
    try:
        return types.GenerateContentConfig(**config_params)
    except Exception:
        # ThinkingConfigを除外して再試行
        if 'thinking_config' in config_params:
            del config_params['thinking_config']
            return types.GenerateContentConfig(**config_params)

def extract_grounding_metadata(response_or_chunk):
    """レスポンスまたはチャンクからグラウンディングメタデータを抽出"""
    grounding_metadata = None
    
    # レスポンスオブジェクトの場合
    if hasattr(response_or_chunk, 'candidates') and response_or_chunk.candidates:
        candidate = response_or_chunk.candidates[0]
        if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
            grounding_metadata = candidate.grounding_metadata
    
    # チャンクオブジェクトの場合
    if hasattr(response_or_chunk, 'grounding_metadata') and response_or_chunk.grounding_metadata:
        grounding_metadata = response_or_chunk.grounding_metadata
    
    # チャンクの候補から取得
    if hasattr(response_or_chunk, 'candidates') and response_or_chunk.candidates:
        candidate = response_or_chunk.candidates[0]
        
        # 候補1: candidate.grounding_metadata
        if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
            grounding_metadata = candidate.grounding_metadata
        
        # 候補2: candidate.content.grounding_metadata
        if hasattr(candidate, 'content') and hasattr(candidate.content, 'grounding_metadata') and candidate.content.grounding_metadata:
            grounding_metadata = candidate.content.grounding_metadata
    
    return grounding_metadata

def handle_rag_error(error, context=""):
    """RAGエラーの統一ハンドリング"""
    error_msg = f"エラーが発生しました: {str(error)}"
    if context:
        print(f"Error in {context}: {error}")
    else:
        print(f"RAG Error: {error}")
    return error_msg

@auth.verify_password
def verify_password(username, password):
    """ユーザー名とパスワードを検証"""
    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        return username
    return None

@auth.error_handler
def auth_error(status):
    """認証エラーハンドラー"""
    return jsonify({'error': 'アクセスが拒否されました。正しいユーザー名とパスワードを入力してください。'}), status

def fix_base64_padding(data):
    """Base64データのパディングを修正"""
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    return data

def validate_and_fix_private_key(private_key):
    """プライベートキーの形式を検証・修正"""
    if not private_key:
        return private_key
    
    # PEM形式のヘッダー・フッターを確認
    if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
        return private_key
    
    # PEM形式のキーを行に分割
    lines = private_key.split('\n')
    if len(lines) < 3:
        return private_key
    
    # ヘッダーとフッターを除いたBase64部分を取得
    base64_lines = []
    for line in lines[1:-1]:  # ヘッダーとフッターを除く
        line = line.strip()
        if line and not line.startswith('-----'):
            base64_lines.append(line)
    
    if not base64_lines:
        return private_key
    
    # Base64文字列を結合
    base64_data = ''.join(base64_lines)
    
    # パディングを修正
    try:
        fixed_base64 = fix_base64_padding(base64_data)
        # Base64デコードをテスト
        base64.b64decode(fixed_base64)
        
        # 修正されたキーを再構築
        fixed_private_key = '-----BEGIN PRIVATE KEY-----\n'
        # 64文字ずつ改行
        for i in range(0, len(fixed_base64), 64):
            fixed_private_key += fixed_base64[i:i+64] + '\n'
        fixed_private_key += '-----END PRIVATE KEY-----'
        
        return fixed_private_key
        
    except Exception as e:
        print(f"Warning: Could not fix private key Base64 padding: {e}")
        return private_key

def setup_google_auth():
    """Google Cloud認証を設定"""
    # 環境変数からサービスアカウントキーのJSONを読み込む
    credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    
    if credentials_json:
        try:
            # JSONの妥当性をチェック
            parsed_json = json.loads(credentials_json)
            
            # 必要なフィールドが含まれているかチェック
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in parsed_json]
            
            if missing_fields:
                print(f"Warning: Missing required fields in Google Cloud credentials: {missing_fields}")
                return
            
            # プライベートキーのBase64パディングを修正
            if 'private_key' in parsed_json:
                original_key = parsed_json['private_key']
                fixed_key = validate_and_fix_private_key(original_key)
                if fixed_key != original_key:
                    print("INFO: Fixed private key Base64 padding")
                    parsed_json['private_key'] = fixed_key
            
            # 環境変数として直接設定（ファイル作成不要）
            os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'] = json.dumps(parsed_json)
                
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in GOOGLE_APPLICATION_CREDENTIALS_JSON: {e}")
            print("Please check the format of your Google Cloud credentials JSON.")
            return
        except Exception as e:
            print(f"Error setting up Google Cloud authentication: {e}")
            return
    
    # 既存のGOOGLE_APPLICATION_CREDENTIALSがある場合はそのまま使用
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and not credentials_json:
        print("Warning: Google Cloud認証情報が設定されていません")
        print("以下の環境変数のいずれかを設定してください:")
        print("- GOOGLE_APPLICATION_CREDENTIALS: サービスアカウントキーファイルのパス")
        print("- GOOGLE_APPLICATION_CREDENTIALS_JSON: サービスアカウントキーのJSON文字列")

# 認証設定を初期化
setup_google_auth()

def create_rag_client():
    """RAGクライアントを作成"""
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="global",
    )
    return client

def extract_date_from_filename(filename):
    """ファイル名から日付を抽出する（_yyyymmdd形式またはyyyymmdd形式）"""
    if not filename:
        return None
    
    # yyyymmdd形式の日付を検索（アンダースコアありまたはなし）
    # パターン1: _yyyymmdd形式（アンダースコアあり）
    # パターン2: yyyymmdd形式（ファイル名の先頭または区切り文字の後）
    date_patterns = [
        r'_(\d{8})(?:\.|_|$)',  # _yyyymmdd形式
        r'(?:^|[^\d])(\d{8})(?:[^\d]|$)',  # yyyymmdd形式（前後に数字以外の文字）
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, filename)
        if match:
            date_str = match.group(1)
            try:
                # 日付の妥当性をチェック
                date_obj = datetime.strptime(date_str, '%Y%m%d')
                
                # 妥当な日付範囲をチェック（1900年〜2100年）
                if 1900 <= date_obj.year <= 2100:
                    return date_obj
            except ValueError:
                # 無効な日付の場合は次のパターンを試す
                continue
    
    return None

def sort_sources_by_date(sources):
    """出典情報を日付順にソート（新しい日付を優先）"""
    def get_sort_key(source):
        title = source.get('title', '')
        uri = source.get('uri', '')
        
        # タイトルとURIの両方から日付を抽出を試みる
        date_from_title = extract_date_from_filename(title)
        date_from_uri = extract_date_from_filename(uri)
        
        # より新しい日付を使用
        extracted_date = None
        if date_from_title and date_from_uri:
            extracted_date = max(date_from_title, date_from_uri)
        elif date_from_title:
            extracted_date = date_from_title
        elif date_from_uri:
            extracted_date = date_from_uri
        
        # 日付が見つからない場合は最も古い日付として扱う
        if extracted_date is None:
            extracted_date = datetime(1900, 1, 1)
        
        # 新しい日付を優先するため、日付を逆順でソート
        return (-extracted_date.timestamp(), title.lower())
    
    return sorted(sources, key=get_sort_key)

def convert_grounding_metadata_to_dict(grounding_metadata):
    """グラウンディングメタデータを辞書形式に変換"""
    if grounding_metadata is None:
        return None
    
    try:
        grounding_chunks = grounding_metadata.grounding_chunks
        
        unsorted_chunks = []
        for i, chunk in enumerate(grounding_chunks):
            chunk_dict = {}
            
            # 基本情報を取得
            if hasattr(chunk, 'retrieved_context') and chunk.retrieved_context:
                retrieved_context = chunk.retrieved_context
                
                # titleを取得
                if hasattr(retrieved_context, 'title') and retrieved_context.title:
                    chunk_dict['title'] = retrieved_context.title
                
                # uriを取得
                if hasattr(retrieved_context, 'uri') and retrieved_context.uri:
                    chunk_dict['uri'] = retrieved_context.uri
            
            # webプロパティも確認（念のため）
            if hasattr(chunk, 'web') and chunk.web:
                if not chunk_dict.get('title') and hasattr(chunk.web, 'title'):
                    chunk_dict['title'] = chunk.web.title
                if not chunk_dict.get('uri') and hasattr(chunk.web, 'uri'):
                    chunk_dict['uri'] = chunk.web.uri
            
            # 直接的なtitle/uriプロパティも確認
            if not chunk_dict.get('title') and hasattr(chunk, 'title'):
                chunk_dict['title'] = chunk.title
            if not chunk_dict.get('uri') and hasattr(chunk, 'uri'):
                chunk_dict['uri'] = chunk.uri
            
            unsorted_chunks.append(chunk_dict)
        
        # 日付でソート
        sorted_chunks = sort_sources_by_date(unsorted_chunks)
        
        result = {
            'grounding_chunks': sorted_chunks
        }
        
        return result
        
    except Exception as e:
        return None

def generate_plan_and_questions(user_message):
    """ユーザーの質問から計画と関連質問を生成"""
    try:
        client = create_rag_client()
        
        planning_prompt = f"""
以下のユーザーの質問に対して、包括的で詳細な回答を提供するための計画を立ててください。

ユーザーの質問: {user_message}

以下の形式で回答してください：

## 調査計画
[この質問に答えるための調査計画を簡潔に説明]

## 関連質問リスト
1. [関連質問1]
2. [関連質問2]
3. [関連質問3]
4. [関連質問4]
5. [関連質問5]

関連質問は以下の観点から作成してください：
- "製品含有化学物質管理"の文脈
- 基本的な定義や概念
- 具体的な事例や応用
- メリット・デメリット
- 最新の動向や課題
- 関連する技術や手法

各質問は独立して回答可能で、元の質問の理解を深めるものにしてください。
"""
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text=planning_prompt)]
            )
        ]
        
        config = create_generate_config(temperature=0.7, include_tools=False)
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        
        if response and response.text:
            return response.text
        else:
            print("WARNING: Empty response from planning model")
            return f"""
## 調査計画
{user_message}について詳細に調査します。

## 関連質問リスト
1. {user_message}の基本的な定義とは何ですか？
2. {user_message}の具体的な事例を教えてください
3. {user_message}のメリットとデメリットは何ですか？
4. {user_message}の最新の動向はどうですか？
5. {user_message}に関連する技術や手法はありますか？
"""
    except Exception as e:
        print(f"Error in generate_plan_and_questions: {e}")
        return f"""
## 調査計画
{user_message}について詳細に調査します。

## 関連質問リスト
1. {user_message}の基本的な定義とは何ですか？
2. {user_message}の具体的な事例を教えてください
3. {user_message}のメリットとデメリットは何ですか？
4. {user_message}の最新の動向はどうですか？
5. {user_message}に関連する技術や手法はありますか？
"""

def generate_default_plan_and_questions(user_message):
    """デフォルトの計画と関連質問を生成"""
    return f"""
## 調査計画
{user_message}について詳細に調査します。

## 関連質問リスト
1. {user_message}の基本的な定義とは何ですか？
2. {user_message}の具体的な事例を教えてください
3. {user_message}のメリットとデメリットは何ですか？
4. {user_message}の最新の動向はどうですか？
5. {user_message}に関連する技術や手法はありますか？
"""

def execute_single_rag_query(question):
    """単一のRAGクエリを実行"""
    try:
        client = create_rag_client()
        
        # システムプロンプトをユーザーメッセージに統合
        combined_message = f"{RAG_SYSTEM_PROMPT}\n\n質問: {question}"
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text=combined_message)]
            )
        ]
        
        config = create_generate_config()
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        
        # グラウンディングメタデータを取得
        grounding_metadata = extract_grounding_metadata(response)
        
        answer_text = response.text if response and response.text else "回答を取得できませんでした。"
        return answer_text, grounding_metadata
        
    except Exception as e:
        return handle_rag_error(e, "execute_single_rag_query"), None

def synthesize_comprehensive_answer(user_message, plan_text, qa_results):
    """計画と各質問の回答を統合して包括的な回答を生成"""
    client = create_rag_client()
    
    qa_text = "\n\n".join([f"**Q: {q}**\nA: {a}" for q, a in qa_results])
    
    synthesis_prompt = f"""
以下の情報を基に、ユーザーの質問に対する包括的で詳細な回答を作成してください。

**重要**: 以下の調査結果のみを使用して回答してください。あなたの一般的な知識や事前学習データは一切使用しないでください。

元の質問: {user_message}

調査計画:
{plan_text}

関連質問と回答:
{qa_text}

以下の要件に従って回答を作成してください：
1. 元の質問に直接答える
2. 関連質問の回答から得られた情報のみを統合する
3. 論理的で読みやすい構成にする
4. 重要なポイントを強調する
5. 具体例があれば含める（ただし上記の調査結果にあるもののみ）
6. Markdown形式で整理する
7. 上記の調査結果にない情報については言及しない
8. 情報が不足している場合は「調査結果では〇〇について詳細な情報が見つかりませんでした」と明記する

回答は以下の構成を参考にしてください：
- 概要・定義
- 詳細説明
- 具体例・事例
- メリット・デメリット
- 最新動向・課題
- まとめ
"""
    
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=synthesis_prompt)]
        )
    ]
    
    # RAGツールを使用して包括的回答を生成
    config = create_generate_config(temperature=0.7, include_tools=True)
    
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        
        if response.text:
            return response.text
        else:
            # RAGツールが失敗した場合のフォールバック
            return f"## 🎯 包括的な回答\n\n{qa_text}\n\n*注: 上記の調査結果を基にした包括的な回答です。*"
            
    except Exception as e:
        print(f"Error in synthesize_comprehensive_answer: {e}")
        # エラー時のフォールバック
        return f"## 🎯 包括的な回答\n\n{qa_text}\n\n*注: 上記の調査結果を基にした包括的な回答です。*"

def generate_deep_response(user_message, generate_questions=False):
    """深掘り機能付きのレスポンス生成"""
    try:
        # ステップ1: 計画立てと関連質問生成
        yield {
            'chunk': '\n## 📋 調査計画を立案中...\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'planning'
        }
        
        if generate_questions:
            # AIによる関連質問生成
            plan_text = generate_plan_and_questions(user_message)
        else:
            # デフォルトの関連質問を使用
            plan_text = generate_default_plan_and_questions(user_message)
        
        if not plan_text:
            plan_text = generate_default_plan_and_questions(user_message)
        
        yield {
            'chunk': f'\n{plan_text}\n\n## 🔍 詳細調査を開始...\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'plan_complete'
        }
        
        # 関連質問を抽出
        questions = []
        try:
            lines = plan_text.split('\n')
            in_questions_section = False
            
            for line in lines:
                if '関連質問' in line:
                    in_questions_section = True
                    continue
                if in_questions_section and line.strip():
                    if line.strip().startswith(('1.', '2.', '3.', '4.', '5.')):
                        question = line.strip()[2:].strip()
                        if question and question not in questions:
                            questions.append(question)
        except Exception as e:
            print(f"Error extracting questions: {e}")
            questions = generate_default_questions(user_message)
        
        # 質問が少ない場合のフォールバック
        if len(questions) < 3:
            questions = generate_default_questions(user_message)
        
        # ステップ2: 各関連質問を順次実行
        qa_results = []
        all_grounding_metadata = []
        all_unique_sources = {}  # 重複を避けるため辞書で管理
        
        for i, question in enumerate(questions[:5], 1):
            yield {
                'chunk': f'\n### 🔍 質問 {i}: {question}\n調査中...\n',
                'done': False,
                'grounding_metadata': None,
                'step': f'query_{i}'
            }
            
            try:
                answer, grounding_metadata = execute_single_rag_query(question)
                
                # 回答が空またはエラーの場合のフォールバック
                if not answer or "エラー" in answer or "取得できません" in answer:
                    answer = f"この質問についての詳細な情報は現在の資料からは見つかりませんでした。"
                
                qa_results.append((question, answer))
                
                # 出典情報を処理
                converted_metadata = None
                if grounding_metadata:
                    all_grounding_metadata.append(grounding_metadata)
                    converted_metadata = convert_grounding_metadata_to_dict(grounding_metadata)
                    
                    # 出典情報を統合（重複を避ける）
                    if converted_metadata and 'grounding_chunks' in converted_metadata:
                        for chunk in converted_metadata['grounding_chunks']:
                            if chunk.get('uri'):
                                all_unique_sources[chunk['uri']] = {
                                    'title': chunk.get('title', 'タイトルなし'),
                                    'uri': chunk['uri']
                                }
                
                # 回答を送信
                yield {
                    'chunk': f'\n**💡 回答 {i}:** {answer}\n',
                    'done': False,
                    'grounding_metadata': converted_metadata,
                    'step': f'answer_{i}'
                }
                
                # 各質問の出典情報を個別に表示
                if converted_metadata and 'grounding_chunks' in converted_metadata:
                    # 出典情報を日付順にソート
                    sorted_chunks = sort_sources_by_date(converted_metadata['grounding_chunks'])
                    
                    sources_text = '\n**📚 この回答の出典:**\n'
                    for j, chunk in enumerate(sorted_chunks, 1):
                        title = chunk.get('title', 'タイトルなし')
                        uri = chunk.get('uri', '')
                        
                        # 日付情報を表示に含める
                        extracted_date = extract_date_from_filename(title)
                        date_info = f" ({extracted_date.strftime('%Y-%m-%d')})" if extracted_date else ""
                        
                        sources_text += f'   {j}. {title}{date_info}\n'
                        if uri:
                            sources_text += f'      📎 {uri}\n'
                    sources_text += '\n'
                    
                    yield {
                        'chunk': sources_text,
                        'done': False,
                        'grounding_metadata': None,
                        'step': f'sources_{i}'
                    }
                    
            except Exception as e:
                print(f"Error in query {i}: {e}")
                error_answer = f"この質問の処理中にエラーが発生しました: {str(e)}"
                qa_results.append((question, error_answer))
                
                yield {
                    'chunk': f'\n**⚠️ 回答 {i}:** {error_answer}\n',
                    'done': False,
                    'grounding_metadata': None,
                    'step': f'error_{i}'
                }
        
        # ステップ3: 包括的な回答の統合
        yield {
            'chunk': '\n## 📝 包括的な回答を作成中...\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'synthesizing'
        }
        
        comprehensive_answer = synthesize_comprehensive_answer(user_message, plan_text, qa_results)
        
        yield {
            'chunk': f'\n## 🎯 包括的な回答\n\n{comprehensive_answer}\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'synthesis_complete'
        }
        
        # 全ての出典情報を統合して表示
        if all_unique_sources:
            # 日付順にソートしてから表示
            sorted_unique_sources = sort_sources_by_date(list(all_unique_sources.values()))
            
            yield {
                'chunk': '\n## 📚 全体の出典情報\n\n',
                'done': False,
                'grounding_metadata': None,
                'step': 'all_sources_header'
            }
            
            sources_summary = ''
            for i, source_info in enumerate(sorted_unique_sources, 1):
                title = source_info.get('title', 'タイトルなし')
                uri = source_info.get('uri', '')
                
                # 日付情報を表示に含める
                extracted_date = extract_date_from_filename(title)
                date_info = f" ({extracted_date.strftime('%Y-%m-%d')})" if extracted_date else ""
                
                sources_summary += f'**{i}. {title}{date_info}**\n'
                sources_summary += f'   📎 {uri}\n\n'
            
            yield {
                'chunk': sources_summary,
                'done': False,
                'grounding_metadata': None,
                'step': 'all_sources_list'
            }
        
        # 最終的な出典情報を統合（JSONとして送信）
        final_grounding_metadata = None
        if all_grounding_metadata:
            # 全ての出典情報を統合し、日付順にソート
            sorted_unique_sources = sort_sources_by_date(list(all_unique_sources.values()))
            final_grounding_metadata = {
                'grounding_chunks': sorted_unique_sources
            }
        
        yield {
            'chunk': '',
            'done': True,
            'grounding_metadata': final_grounding_metadata,
            'step': 'complete'
        }
        
    except Exception as e:
        print(f"Deep response generation error: {e}")
        yield {
            'chunk': f'\n❌ エラーが発生しました: {str(e)}\n通常モードで回答を試みます...\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'error'
        }
        
        # エラー時は通常モードにフォールバック
        try:
            for chunk_data in generate_response(user_message):
                yield chunk_data
        except Exception as fallback_error:
            print(f"Fallback error: {fallback_error}")
            yield {
                'chunk': f'\n❌ 回答の生成に失敗しました: {handle_rag_error(fallback_error)}\n',
                'done': True,
                'grounding_metadata': None,
                'step': 'fallback_error'
            }

def generate_response(user_message):
    """ユーザーメッセージに対してRAGを使用してレスポンスを生成"""
    client = create_rag_client()
    
    # システムプロンプトをユーザーメッセージに統合
    combined_message = f"{RAG_SYSTEM_PROMPT}\n\n質問: {user_message}"
    
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=combined_message)
            ]
        )
    ]
    
    # GenerateContentConfigを作成
    config = create_generate_config(temperature=1, top_p=1, seed=0, include_thinking=True)
    
    full_response = ""
    grounding_metadata = None
    
    for chunk in client.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    ):
        if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
            continue
        
        # テキストを蓄積
        full_response += chunk.text
        
        # グラウンディングメタデータを取得
        grounding_metadata = extract_grounding_metadata(chunk)
        
        yield {
            'chunk': chunk.text,
            'done': False,
            'grounding_metadata': None
        }
    
    # 最後に出典情報を送信（辞書形式に変換）
    converted_metadata = convert_grounding_metadata_to_dict(grounding_metadata)
    
    yield {
        'chunk': '',
        'done': True,
        'grounding_metadata': converted_metadata
    }

@app.route('/')
@auth.login_required
def index():
    """メインページ"""
    return render_template('index.html')

@app.route('/health')
def health():
    """軽量なヘルスチェックエンドポイント"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/chat', methods=['POST'])
@auth.login_required
def chat():
    """チャットエンドポイント"""
    data = request.json
    user_message = data.get('message', '')
    use_deep_mode = data.get('deep_mode', False)
    generate_questions = data.get('generate_questions', False)
    
    if not user_message:
        return jsonify({'error': 'メッセージが空です'}), 400
    
    def generate():
        try:
            if use_deep_mode:
                # 深掘りモードを使用
                for chunk_data in generate_deep_response(user_message, generate_questions):
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
            else:
                # 通常モードを使用
                for chunk_data in generate_response(user_message):
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            print(f"Error in chat endpoint: {e}")
            error_data = {
                'chunk': handle_rag_error(e, "chat endpoint"),
                'done': True,
                'grounding_metadata': None
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        finally:
            # 正常・異常終了問わずメモリクリーンアップ
            gc.collect()
    
    return Response(generate(), mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True) 