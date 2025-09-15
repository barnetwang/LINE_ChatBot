import os
import json
import base64
import hashlib
import hmac
import time
import jwt
import requests

from flask import Blueprint, request, jsonify, Response, render_template, abort
from werkzeug.utils import secure_filename
from jwt.algorithms import RSAAlgorithm
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, ReplyMessageRequest
from . import rag_chat, AVAILABLE_MODELS, app_config, BOT_DISPLAY_NAME

from . import rag_chat, AVAILABLE_MODELS, app_config

main = Blueprint('main', __name__)

# --- Web UI 的路由 ---
@main.route('/')
def index():
    return render_template('index.html')

@main.route('/api/models', methods=['GET'])
def get_models_and_settings():
    if not rag_chat:
        return jsonify({"error": "RAG service not initialized"}), 503
    return jsonify({
        "models": AVAILABLE_MODELS,
        "current_model": rag_chat.current_llm_model,
        "history_enabled": rag_chat.use_history
    })

@main.route('/api/set_model', methods=['POST'])
def set_model():
    data = request.get_json()
    model_name = data.get('model')
    if not model_name or model_name not in AVAILABLE_MODELS:
        return jsonify({"success": False, "error": "無效或不可用的模型名稱"}), 400
    success = rag_chat.set_llm_model(model_name)
    if success:
        return jsonify({"success": True, "message": f"模型成功切換至 {model_name}"})
    else:
        return jsonify({"success": False, "error": "伺服器切換模型時發生內部錯誤"}), 500

@main.route('/api/set_history', methods=['POST'])
def set_history():
    data = request.get_json()
    enabled = data.get('enabled')
    if not isinstance(enabled, bool):
        return jsonify({"success": False, "error": "無效的參數"}), 400
    rag_chat.set_history_retrieval(enabled)
    return jsonify({"success": True})

@main.route('/ask', methods=['GET'])
def handle_ask():
    question = request.args.get('question')
    if not question:
        return Response("Error: No question provided", status=400)
    if not rag_chat or not rag_chat.llm:
        return Response("Error: LLM not available", status=503)
    return Response(rag_chat.ask(question, user_id='web_user', stream=True), mimetype='text/event-stream')

@main.route('/api/records', methods=['GET'])
def get_all_records():
    try:
        data = rag_chat.vector_db.get(include=["metadatas", "documents"])
        records = [
            {
                "id": data['ids'][i],
                "content": data['documents'][i],
                "metadata": data['metadatas'][i]
            } for i in range(len(data['ids'])) if data['documents'][i] != 'start'
        ]
        return jsonify(sorted(records, key=lambda x: x['id'], reverse=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/api/delete', methods=['POST'])
def delete_record():
    data = request.get_json()
    doc_id = data.get('id')
    if not doc_id:
        return jsonify({"error": "請求中缺少 ID", "success": False}), 400
    try:
        rag_chat.vector_db.delete([doc_id])
        return jsonify({"success": True, "message": f"成功刪除 ID: {doc_id}"})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@main.route('/favicon.ico')
def favicon():
    return '', 204

@main.route('/api/upload_document', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "請求中未包含檔案"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "未選取檔案"}), 400

    upload_folder = 'uploads'
    os.makedirs(upload_folder, exist_ok=True)
    filename = secure_filename(file.filename)
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)

    try:
        rag_chat.add_document(file_path, user_id='global_document')
        return jsonify({"success": True, "message": f"檔案 '{filename}' 已成功上傳並處理。"})
    except Exception as e:
        print(f"上傳處理失敗: {e}")
        return jsonify({"success": False, "error": f"處理檔案時發生錯誤: {e}"}), 500


# --- LINE Bot 的路由 ---
channel_access_token = None
token_expiry_time = 0

def verify_signature(body_str, signature_header):
    if not signature_header:
        print("Signature header is missing.")
        return False
    try:
        hash_val = hmac.new(app_config['CHANNEL_SECRET'].encode('utf-8'),
                            body_str.encode('utf-8'), hashlib.sha256).digest()
        signature = base64.b64encode(hash_val)
        return hmac.compare_digest(signature, signature_header.encode('utf-8'))
    except Exception as e:
        print(f"Error during signature verification: {e}")
        return False


def get_channel_access_token():
    global channel_access_token, token_expiry_time

    if channel_access_token and time.time() < token_expiry_time - 300:
        return channel_access_token

    print("Generating new channel access token...")

    try:
        with open(app_config['PRIVATE_KEY_PATH'], 'r') as f:
            private_key_data = json.load(f)
    except FileNotFoundError:
        print(
            f"Error: Private key file not found at {app_config['PRIVATE_KEY_PATH']}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from private key file.")
        return None

    header = {
        "alg": "RS256",
        "typ": "JWT",
        "kid": app_config['KEY_ID']
    }
    payload = {
        "iss": app_config['CHANNEL_ID'],
        "sub": app_config['CHANNEL_ID'],
        "aud": "https://api.line.me/",
        "exp": int(time.time()) + (30 * 60),
        "token_exp": 60 * 60 * 24 * 30
    }

    private_key = RSAAlgorithm.from_jwk(private_key_data)
    signed_jwt = jwt.encode(payload, private_key,
                            algorithm="RS256", headers=header)

    url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'client_credentials',
        'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
        'client_assertion': signed_jwt
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()

        channel_access_token = token_data['access_token']
        token_expiry_time = time.time() + token_data['expires_in']

        print("Successfully obtained new channel access token.")
        return channel_access_token
    except requests.exceptions.RequestException as e:
        print(f"Error getting channel access token from LINE API: {e}")
        if e.response:
            print(f"Response body: {e.response.text}")
        return None

@main.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    if not verify_signature(body, signature):
        abort(400)
    
    data = json.loads(body)
    for event in data.get('events', []):
        if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
            
            source_type = event.get('source', {}).get('type')
            message_text = event.get('message', {}).get('text', '')

            if source_type == 'user':
                print(f"💬 收到來自「一對一聊天」的訊息，直接處理。")
                handle_line_message(event)
            elif source_type in ['group', 'room'] and BOT_DISPLAY_NAME and (f"@{BOT_DISPLAY_NAME}" in message_text):
                print(f"👥 收到來自「群組」的訊息，且偵測到 @{BOT_DISPLAY_NAME}，開始處理。")
                handle_line_message(event)
            else:
                print(f"🔇 收到來自「群組」的一般訊息，已忽略。")
    return 'OK'

def handle_line_message(event_dict):
    access_token = get_channel_access_token()
    configuration = Configuration(access_token=access_token)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        original_message = event_dict['message']['text']
        reply_token = event_dict['replyToken']
        user_id = event_dict['source']['userId']

    try:
        if BOT_DISPLAY_NAME:
            cleaned_message = original_message.replace(f"@{BOT_DISPLAY_NAME}", "").strip()
        else:
            cleaned_message = original_message
        
        print(f"🧼 清理後的訊息: '{cleaned_message}'")
        
        reply_text = rag_chat.ask(
            question=cleaned_message,
            user_id=user_id
        )
        
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

    except Exception as e:
        print(f"處理訊息或回覆時發生嚴重錯誤: {e}")
        try:
            error_message = "抱歉，我的 AI 大腦好像有點短路，我已經通知我的主人了，請稍後再試一次。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=error_message)]
                )
            )
        except Exception as inner_e:
            print(f"連回覆錯誤訊息都失敗了: {inner_e}")
