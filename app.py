import os
import time
import jwt
from jwt.algorithms import RSAAlgorithm
import requests
import json
import ollama

from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# --- 1. 從 LINE Developer Console Messaging API 取得的資訊 ---
CHANNEL_ID = '2008069492'
CHANNEL_SECRET = '880889c8781f1b358321b1d655ec51cf'
# --- 註冊公鑰後取得的 Key ID ---
KEY_ID = '4b3e0f9a-1a5e-4475-88b0-5f3f7b460c0c' 
# --- 私鑰檔案的路徑 (現在是 .json) ---
PRIVATE_KEY_PATH = './private_key.json'

channel_access_token = None
token_expires_at = 0

def get_channel_access_token():
    global channel_access_token, token_expires_at
    
    if time.time() < token_expires_at:
        return channel_access_token

    print("Generating new token with RS256...")
    token_endpoint = 'https://api.line.me/oauth2/v2.1/token'

    # 用 JWK 格式的私鑰 (不變)
    with open(PRIVATE_KEY_PATH, 'r') as f:
        private_key_jwk = f.read()
    private_key = RSAAlgorithm.from_jwk(private_key_jwk)

    headers = {
        "alg": "RS256",
        "typ": "JWT",
        "kid": KEY_ID
    }
    payload = {
        "iss": CHANNEL_ID,  
        "sub": CHANNEL_ID,  
        "aud": "https://api.line.me/",  
        "exp": int(time.time()) + 60 * 30,  
        "token_exp": 60 * 60 * 24 * 30  
    }

    assertion = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)

    request_data = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion
    }

    response = requests.post(token_endpoint, data=request_data)
    response_data = response.json()

    if "access_token" in response_data:
        channel_access_token = response_data["access_token"]
        token_expires_at = time.time() + response_data["expires_in"] - 300
        print("Successfully obtained new token.")
        return channel_access_token
    else:
        print("Error getting token:", response_data)
        raise Exception("Could not get access token.")

app = Flask(__name__)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Please check your channel secret.")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    access_token = get_channel_access_token()
    configuration = Configuration(access_token=access_token)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        user_message = event.message.text
        print(f"接收到使用者訊息: {user_message}")

        try:
            response = ollama.chat(
                model='qwen3:30b-a3b', #設定你的LLM model
                messages=[{'role': 'user', 'content': user_message}]
            )
            reply_text = response['message']['content']
            print(f"Ollama AI 回覆: {reply_text}")
        except Exception as e:
            print(f"呼叫 Ollama 時發生錯誤: {e}")
            reply_text = "抱歉，我的 AI 大腦好像有點短路，請稍後再試一次。"
        
        # --- 使用 Reply Message API ---
        print("Attempting to REPLY message...")
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
        print("Reply message request sent successfully!")

if __name__ == "__main__":
    get_channel_access_token()
    app.run(port=5001)