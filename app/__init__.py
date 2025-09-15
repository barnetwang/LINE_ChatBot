import os
import time
import jwt
import requests
from flask import Flask
from config import Config
from .services import ConversationalRAG, get_ollama_models

from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi
)
from jwt.algorithms import RSAAlgorithm

rag_chat = None
AVAILABLE_MODELS = []
app_config = None
BOT_DISPLAY_NAME = None


def create_app(config_class=Config):
    global rag_chat, AVAILABLE_MODELS, app_config

    app = Flask(__name__, instance_relative_config=True,
                template_folder='../templates')
    app.config.from_object(config_class)
    app_config = app.config

    print("--- 正在啟動整合 RAG 伺服器，請稍候... ---")

    AVAILABLE_MODELS = get_ollama_models(app.config['OLLAMA_BASE_URL'])

    if not AVAILABLE_MODELS:
        llm_model = None
    else:
        llm_model = app.config['DEFAULT_MODEL']
        if llm_model not in AVAILABLE_MODELS:
            llm_model = AVAILABLE_MODELS[0]

    rag_chat = ConversationalRAG(
        persist_directory=app.config['PERSIST_DIRECTORY'],
        embedding_model_name=app.config['EMBEDDING_MODEL_NAME'],
        llm_model=llm_model,
        ollama_base_url=app.config['OLLAMA_BASE_URL'],
    )
    print("🤖 正在從 LINE API 獲取機器人資訊...")
    try:
        token_endpoint = 'https://api.line.me/oauth2/v2.1/token'
        with open(app.config['PRIVATE_KEY_PATH'], 'r') as f:
            private_key_jwk = f.read()
        private_key = RSAAlgorithm.from_jwk(private_key_jwk)
        headers = {"alg": "RS256", "typ": "JWT", "kid": app.config['KEY_ID']}
        payload = {
            "iss": app.config['CHANNEL_ID'],
            "sub": app.config['CHANNEL_ID'],
            "aud": "https://api.line.me/",
            "exp": int(time.time()) + 60 * 30,
            "token_exp": 60 * 60 * 24 * 30
        }
        assertion = jwt.encode(payload, private_key,
                               algorithm="RS256", headers=headers)
        request_data = {"grant_type": "client_credentials", "client_assertion_type":
                        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": assertion}
        response = requests.post(token_endpoint, data=request_data)
        response_data = response.json()

        if "access_token" in response_data:
            access_token = response_data["access_token"]
            configuration = Configuration(access_token=access_token)
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                bot_info = line_bot_api.get_bot_info()
                BOT_DISPLAY_NAME = bot_info.display_name
                print(f"✅ 機器人名稱獲取成功: '{BOT_DISPLAY_NAME}'")
        else:
            raise Exception(f"獲取臨時 token 失敗: {response_data}")
    except Exception as e:
        print(f"❌ 獲取機器人名稱失敗: {e}")
        print("⚠️ 警告: 將無法在群組中透過 @ 標籤回應。")
    print("--- RAG 引擎已就緒，伺服器正在運行 ---")

    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
