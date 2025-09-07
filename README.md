Python + Ollama LINE Chatbot
這是一個完全使用 Python 和本地端 Ollama 大型語言模型 (LLM) 來建立 LINE 聊天機器人的專案。
它實現了一個完全私有、無 API 費用、且反應迅速的 AI 聊天機器人。所有的 AI 運算都在您自己的機器上完成，確保了最高的資料隱私性。
架構
整個系統的運作流程非常直接：
code
Code
[使用者] <--> [LINE Platform] <--> [ngrok] <--> [本地 Python Flask 伺服器] <--> [本地 Ollama LLM]
功能特性
完全本地化: AI 模型運行在您自己的硬體上，無需依賴任何第三方 API。
資料隱私: 所有對話內容都不會離開您的伺服器。
零 API 成本: 除了可選的伺服器託管費用，沒有任何 API 調用費用。
高度客製化: 您可以輕鬆更換或微調 Ollama 中的任何模型，以滿足特定需求。
環境準備 (Prerequisites)
在開始之前，請確保您已經安裝了以下軟體：
Python 3.8+: 官方網站
Ollama: 官方網站
ngrok: 官方網站 (用於在開發階段將您的本地伺服器暴露到公網)
安裝步驟
Clone 或下載本專案
安裝必要的 Python 函式庫:
code
Bash
pip install flask ollama "pyjwt[crypto]" requests line-bot-sdk jwcrypto
下載一個對話模型:
強烈建議使用 llama3 以獲得最佳的聊天體驗。
code
Bash
ollama pull llama3
關鍵步驟：LINE Developers Console 的正確設定 (避免陷阱)
這一步是整個專案中最關鍵、也最容易出錯的地方。請嚴格按照以下順序操作。
1. 建立 Provider 和 Channel
前往 LINE Developers Console。
建立一個新的 Provider (服務提供者)。
在該 Provider 下，建立一個新的 Channel，並選擇 Messaging API 類型。
2. ‼️‼️ 世紀大陷阱：在「正確的」頁面取得金鑰 ‼️‼️
LINE 的後台有兩個地方都顯示了 Channel Secret，但只有一個是正確的！
❌ 錯誤的地方: Basic settings (基本設定) 分頁。請不要使用這裡的任何金鑰！
✅ 正確的地方: Messaging API 分頁。
所有 Webhook 驗證和 API 呼叫，都必須使用 Messaging API 分頁中的金鑰。
![alt text](https://i.imgur.com/uR0Jspg.png)

(這張由您提供的、價值連城的對比圖，揭示了問題的根源)
3. 產生並註冊金鑰對 (Assertion Signing Key)
我們需要一對公鑰和私鑰來向 LINE API 證明我們的身分。
在您的專案資料夾中，建立一個名為 generate_keys.py 的檔案，並貼上以下內容：
code
Python
# generate_keys.py
from jwcrypto import jwk
import json

# 產生一對全新的 RSA 金鑰
key = jwk.JWK.generate(kty='RSA', alg='RS256', use='sig', size=2048)

# 匯出 JWK 格式的私鑰和公鑰
private_key_json = key.export_private()
public_key_json = key.export_public()

# 將私鑰儲存到檔案中
with open('private_key.json', 'w') as f:
    f.write(private_key_json)
print("✅ 成功！ 'private_key.json' 已經建立。")

# 為了方便複製，將公鑰格式化後印出
print("\n⬇️ --- 請複製以下的「公鑰 JSON」並註冊到 LINE 後台 --- ⬇️\n")
print(json.dumps(json.loads(public_key_json), indent=2))
print("\n⬆️ --- 請複製以上的「公鑰 JSON」並註冊到 LINE 後台 --- ⬆️")
執行這個腳本：
code
Bash
python generate_keys.py
儲存私鑰: 腳本會自動在您的資料夾中建立 private_key.json 檔案。
註冊公鑰:
完整複製終端機印出的公鑰 JSON。
回到 LINE Developers Console，進入 Tomato-B (Messaging API) Channel 的 Messaging API 分頁。
往下找到 "Assertion signing key"，點擊 "Register a public key"。
將複製的公鑰 JSON 貼上並註冊。
註冊成功後，您會得到一個新的 Key ID。
4. 設定回應模式 (解決 403 Forbidden 權限問題)
這是另一個關鍵陷阱。您必須將官方帳號設定為純粹的「Bot 模式」。
前往 LINE Official Account Manager (注意，這是另一個後台)。
選擇您的機器人帳號。
點擊右上角的 設定 > 左邊選單的 回應設定。
進行以下設定：
聊天: 必須關閉 (灰色)。
Webhook: 必須開啟 (綠色)。
![alt text](https://i.imgur.com/Wd8J5eZ.png)

(正確的回應模式設定)
運行您的 AI 機器人
填寫金鑰:
打開您最終版的 Python 檔案 (例如 app_graduate.py)，將您從正確位置取得的 CHANNEL_ID, CHANNEL_SECRET, 和 KEY_ID 填入對應的變數中。
啟動本地伺服器:
code
Bash
python app_graduate.py
您應該會看到 Successfully obtained new token. 的訊息。
啟動 ngrok:
打開一個新的終端機視窗，執行：
code
Bash
./ngrok http 5001
複製 ngrok 提供的 HTTPS Forwarding 網址。
設定 Webhook URL:
回到 LINE Developers Console 的 Messaging API 分頁。
在 "Webhook URL" 欄位，貼上您複製的 ngrok 網址，並在結尾加上 /callback。
範例: https://xxxxxxxx.ngrok-free.app/callback
儲存並確保 "Use webhook" 是啟用的。
開始對話:
用您的手機 LINE App，掃描 QR Code 將您的機器人加為好友，然後開始與您的本地端 AI 對話！
專案檔案結構
code
Code
.
├── app_graduate.py       # 您的主應用程式
├── private_key.json      # 自動產生的私鑰 (切勿外洩)
├── generate_keys.py      # 用於產生金鑰對的輔助腳本
└── README.md             # 本說明檔案
