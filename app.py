from flask import Flask, request, jsonify, render_template, Response
from google import genai
from google.genai import types
import json
import os
import asyncio
import time
import re
from datetime import datetime
import tempfile

app = Flask(__name__)

# 環境変数から設定を読み込み
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT', 'dotd-development-division')
RAG_CORPUS = os.environ.get('RAG_CORPUS', f'projects/{PROJECT_ID}/locations/us-central1/ragCorpora/3458764513820540928')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

def setup_google_auth():
    """Google Cloud認証を設定"""
    # 環境変数からサービスアカウントキーのJSONを読み込む
    credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    if credentials_json:
        # JSONをファイルに書き込んで認証設定
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(credentials_json)
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = f.name
    
    # 既存のGOOGLE_APPLICATION_CREDENTIALSがある場合はそのまま使用
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and not credentials_json:
        print("Warning: Google Cloud認証情報が設定されていません")

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
    """GroundingMetadataオブジェクトを辞書に変換し、日付順にソート"""
    if not grounding_metadata:
        print("DEBUG: grounding_metadata is None")
        return None
    
    print(f"DEBUG: grounding_metadata type: {type(grounding_metadata)}")
    print(f"DEBUG: grounding_metadata attributes: {dir(grounding_metadata)}")
    
    result = {}
    
    # grounding_chunksを処理
    if hasattr(grounding_metadata, 'grounding_chunks') and grounding_metadata.grounding_chunks:
        print(f"DEBUG: Found {len(grounding_metadata.grounding_chunks)} grounding chunks")
        unsorted_chunks = []
        
        for i, chunk in enumerate(grounding_metadata.grounding_chunks):
            print(f"DEBUG: Processing chunk {i}: {type(chunk)}")
            print(f"DEBUG: Chunk attributes: {dir(chunk)}")
            
            chunk_dict = {}
            
            # retrieved_contextからtitleとuriを取得
            if hasattr(chunk, 'retrieved_context') and chunk.retrieved_context:
                print(f"DEBUG: Found retrieved_context: {type(chunk.retrieved_context)}")
                retrieved_context = chunk.retrieved_context
                
                # titleを取得
                if hasattr(retrieved_context, 'title') and retrieved_context.title:
                    chunk_dict['title'] = retrieved_context.title
                    print(f"DEBUG: Found title in retrieved_context: {retrieved_context.title}")
                
                # uriを取得
                if hasattr(retrieved_context, 'uri') and retrieved_context.uri:
                    chunk_dict['uri'] = retrieved_context.uri
                    print(f"DEBUG: Found uri in retrieved_context: {retrieved_context.uri}")
            
            # webプロパティも確認（念のため）
            if hasattr(chunk, 'web') and chunk.web:
                print(f"DEBUG: Found web property: {chunk.web}")
                if not chunk_dict.get('title') and hasattr(chunk.web, 'title'):
                    chunk_dict['title'] = chunk.web.title
                if not chunk_dict.get('uri') and hasattr(chunk.web, 'uri'):
                    chunk_dict['uri'] = chunk.web.uri
            
            # 直接的なtitle/uriプロパティも確認
            if not chunk_dict.get('title') and hasattr(chunk, 'title'):
                chunk_dict['title'] = chunk.title
                print(f"DEBUG: Found direct title: {chunk.title}")
            if not chunk_dict.get('uri') and hasattr(chunk, 'uri'):
                chunk_dict['uri'] = chunk.uri
                print(f"DEBUG: Found direct uri: {chunk.uri}")
            
            # 日付情報を抽出してデバッグ出力
            if chunk_dict.get('title'):
                extracted_date = extract_date_from_filename(chunk_dict['title'])
                if extracted_date:
                    print(f"DEBUG: Extracted date from title '{chunk_dict['title']}': {extracted_date.strftime('%Y-%m-%d')}")
                else:
                    print(f"DEBUG: No date found in title '{chunk_dict['title']}'")
            
            unsorted_chunks.append(chunk_dict)
        
        # 日付順にソート（新しい日付を優先）
        sorted_chunks = sort_sources_by_date(unsorted_chunks)
        result['grounding_chunks'] = sorted_chunks
        
        print(f"DEBUG: Sorted chunks by date:")
        for i, chunk in enumerate(sorted_chunks):
            title = chunk.get('title', 'タイトルなし')
            date = extract_date_from_filename(title)
            date_str = date.strftime('%Y-%m-%d') if date else '日付なし'
            print(f"  {i+1}. {title} ({date_str})")
        
    else:
        print("DEBUG: No grounding_chunks found")
    
    print(f"DEBUG: Final result: {result}")
    return result

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
        
        config = types.GenerateContentConfig(
            temperature=0.7,
            top_p=0.9,
            max_output_tokens=1000,
        )
        
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

def execute_single_rag_query(question):
    """単一のRAGクエリを実行"""
    try:
        client = create_rag_client()
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text=question)]
            )
        ]
        
        tools = [
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

        config = types.GenerateContentConfig(
            temperature=0.8,
            top_p=0.9,
            max_output_tokens=2000,
            tools=tools,
        )
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        
        # グラウンディングメタデータを取得
        grounding_metadata = None
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                grounding_metadata = candidate.grounding_metadata
        
        answer_text = response.text if response and response.text else "回答を取得できませんでした。"
        return answer_text, grounding_metadata
        
    except Exception as e:
        print(f"Error in execute_single_rag_query: {e}")
        return f"エラーが発生しました: {str(e)}", None

def synthesize_comprehensive_answer(user_message, plan_text, qa_results):
    """計画と各質問の回答を統合して包括的な回答を生成"""
    client = create_rag_client()
    
    qa_text = "\n\n".join([f"**Q: {q}**\nA: {a}" for q, a in qa_results])
    
    synthesis_prompt = f"""
以下の情報を基に、ユーザーの質問に対する包括的で詳細な回答を作成してください。

元の質問: {user_message}

調査計画:
{plan_text}

関連質問と回答:
{qa_text}

以下の要件に従って回答を作成してください：
1. 元の質問に直接答える
2. 関連質問の回答から得られた情報を統合する
3. 論理的で読みやすい構成にする
4. 重要なポイントを強調する
5. 具体例があれば含める
6. Markdown形式で整理する

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
    
    config = types.GenerateContentConfig(
        temperature=0.7,
        top_p=0.9,
        max_output_tokens=4000,
    )
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    
    return response.text

def generate_deep_response(user_message):
    """深掘り機能付きのレスポンス生成"""
    try:
        # ステップ1: 計画立てと関連質問生成
        yield {
            'chunk': '\n## 📋 調査計画を立案中...\n',
            'done': False,
            'grounding_metadata': None,
            'step': 'planning'
        }
        
        plan_text = generate_plan_and_questions(user_message)
        
        if not plan_text:
            plan_text = f"""
## 調査計画
{user_message}について詳細に調査します。

## 関連質問リスト
1. {user_message}の基本的な定義とは何ですか？
2. {user_message}の具体的な事例を教えてください
3. {user_message}のメリットとデメリットは何ですか？
4. {user_message}の最新の動向はどうですか？
5. {user_message}に関連する技術や手法はありますか？
"""
        
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
            questions = [
                f"{user_message}の基本的な定義とは何ですか？",
                f"{user_message}の具体的な事例を教えてください",
                f"{user_message}のメリットとデメリットは何ですか？",
                f"{user_message}の最新の動向はどうですか？",
                f"{user_message}に関連する技術や手法はありますか？"
            ]
        
        # 質問が少ない場合のフォールバック
        if len(questions) < 3:
            questions = [
                f"{user_message}の基本的な定義とは何ですか？",
                f"{user_message}の具体的な事例を教えてください",
                f"{user_message}のメリットとデメリットは何ですか？",
                f"{user_message}の最新の動向はどうですか？",
                f"{user_message}に関連する技術や手法はありますか？"
            ]
        
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
            
            answer, grounding_metadata = execute_single_rag_query(question)
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
                'chunk': f'\n❌ 回答の生成に失敗しました: {str(fallback_error)}\n',
                'done': True,
                'grounding_metadata': None,
                'step': 'fallback_error'
            }

def generate_response(user_message):
    """ユーザーメッセージに対してRAGを使用してレスポンスを生成"""
    client = create_rag_client()
    
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=user_message)
            ]
        )
    ]
    tools = [
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

    # GenerateContentConfigを作成
    config_params = {
        'temperature': 1,
        'top_p': 1,
        'seed': 0,
        'max_output_tokens': 65535,
        'safety_settings': [
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF"
            )
        ],
        'tools': tools,
    }
    
    # ThinkingConfigが利用可能な場合のみ追加
    try:
        if hasattr(types, 'ThinkingConfig'):
            config_params['thinking_config'] = types.ThinkingConfig(
                thinking_budget=-1,
            )
    except AttributeError:
        pass  # ThinkingConfigが利用できない場合は無視
    
    generate_content_config = types.GenerateContentConfig(**config_params)

    full_response = ""
    grounding_metadata = None
    
    print(f"DEBUG: Starting generation for message: {user_message}")
    
    for chunk in client.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=contents,
        config=generate_content_config,
    ):
        print(f"DEBUG: Raw chunk: {chunk}")
        
        if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
            print("DEBUG: Skipping chunk - no content")
            continue
        
        print(f"DEBUG: Chunk type: {type(chunk)}")
        print(f"DEBUG: Chunk attributes: {[attr for attr in dir(chunk) if not attr.startswith('_')]}")
        
        # テキストを蓄積
        full_response += chunk.text
        print(f"DEBUG: Added text: {chunk.text[:100]}...")
        
        # 全ての可能な場所でグラウンディングメタデータを探す
        candidate = chunk.candidates[0]
        print(f"DEBUG: Candidate attributes: {[attr for attr in dir(candidate) if not attr.startswith('_')]}")
        
        # 候補1: candidate.grounding_metadata
        if hasattr(candidate, 'grounding_metadata'):
            print(f"DEBUG: candidate.grounding_metadata exists: {candidate.grounding_metadata}")
            if candidate.grounding_metadata:
                print("DEBUG: Found grounding_metadata in candidate")
                grounding_metadata = candidate.grounding_metadata
        
        # 候補2: chunk.grounding_metadata
        if hasattr(chunk, 'grounding_metadata'):
            print(f"DEBUG: chunk.grounding_metadata exists: {chunk.grounding_metadata}")
            if chunk.grounding_metadata:
                print("DEBUG: Found grounding_metadata in chunk")
                grounding_metadata = chunk.grounding_metadata
            
        # 候補3: candidate.content.grounding_metadata
        if hasattr(candidate.content, 'grounding_metadata'):
            print(f"DEBUG: candidate.content.grounding_metadata exists: {candidate.content.grounding_metadata}")
            if candidate.content.grounding_metadata:
                print("DEBUG: Found grounding_metadata in candidate.content")
                grounding_metadata = candidate.content.grounding_metadata
        
        # 候補4: 全体の構造を確認
        print(f"DEBUG: Full candidate structure:")
        for attr in dir(candidate):
            if not attr.startswith('_'):
                try:
                    value = getattr(candidate, attr)
                    print(f"  {attr}: {type(value)} - {value}")
                except:
                    print(f"  {attr}: <error accessing>")
        
        yield {
            'chunk': chunk.text,
            'done': False,
            'grounding_metadata': None
        }
    
    print(f"DEBUG: Final grounding_metadata: {grounding_metadata}")
    
    # 最後に出典情報を送信（辞書形式に変換）
    converted_metadata = convert_grounding_metadata_to_dict(grounding_metadata)
    print(f"DEBUG: Converted metadata: {converted_metadata}")
    
    yield {
        'chunk': '',
        'done': True,
        'grounding_metadata': converted_metadata
    }

@app.route('/')
def index():
    """メインページ"""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """チャットエンドポイント"""
    data = request.json
    user_message = data.get('message', '')
    use_deep_mode = data.get('deep_mode', False)
    
    if not user_message:
        return jsonify({'error': 'メッセージが空です'}), 400
    
    def generate():
        try:
            if use_deep_mode:
                # 深掘りモードを使用
                for chunk_data in generate_deep_response(user_message):
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
            else:
                # 通常モードを使用
                for chunk_data in generate_response(user_message):
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            print(f"Error in chat endpoint: {e}")
            error_data = {
                'chunk': f'エラーが発生しました: {str(e)}',
                'done': True,
                'grounding_metadata': None
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    
    return Response(generate(), mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True) 