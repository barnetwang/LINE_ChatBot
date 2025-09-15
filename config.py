import os

class Config:
    # RAG 相關設定
    EMBEDDING_MODEL_NAME = "shibing624/text2vec-base-chinese"
    PERSIST_DIRECTORY = "chroma_db"
    OLLAMA_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3" # 您的預設對話模型

    # LINE 金鑰 (從環境變數讀取，如果找不到則使用後面的預設值)
    CHANNEL_ID = os.environ.get('LINE_CHANNEL_ID', '你的Channel ID')
    CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '你的 Channel Secret')
    KEY_ID = os.environ.get('LINE_KEY_ID', '你產生的公鑰 ID')
    PRIVATE_KEY_PATH = './private_key.json'
