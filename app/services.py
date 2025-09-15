import os
import json
import re
import requests
from datetime import datetime
from langchain_ollama.llms import OllamaLLM
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain.prompts import PromptTemplate
from langchain_community.document_loaders import UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

def get_ollama_models(ollama_base_url="http://localhost:11434"):
    try:
        response = requests.get(f"{ollama_base_url}/api/tags")
        response.raise_for_status()
        models_data = response.json().get("models", [])
        return [model["name"] for model in models_data]
    except requests.exceptions.ConnectionError:
        print(f"❌ 錯誤：無法連接到 Ollama 服務 ({ollama_base_url})。請確認 Ollama 正在運行。")
        return []
    except Exception as e:
        print(f"❌ 獲取 Ollama 模型時發生錯誤: {e}")
        return []

class ConversationalRAG:
    def __init__(self, persist_directory, embedding_model_name, llm_model, ollama_base_url,
                 use_history=True, history_summary_threshold=2000):
        self.persist_directory = persist_directory
        self.use_history = use_history
        self.ollama_base_url = ollama_base_url
        self.history_summary_threshold = history_summary_threshold

        print("正在初始化 Embedding 模型...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model_name, model_kwargs={'device': 'cpu'})

        print("正在初始化/載入向量資料庫...")
        if not os.path.exists(self.persist_directory):
            print("找不到現有資料庫，將創建一個新的。")
            dummy_doc = Document(page_content="start", metadata={
                                 "source": "initialization", "user_id": "system"})
            self.vector_db = Chroma.from_documents(
                [dummy_doc], self.embeddings, persist_directory=self.persist_directory)
        else:
            print("找到現有資料庫，正在載入...")
            self.vector_db = Chroma(
                persist_directory=self.persist_directory, embedding_function=self.embeddings)

        self.llm = None
        self.current_llm_model = None
        self.set_llm_model(llm_model)

        self.main_prompt = PromptTemplate(
            template='''你是一個 AI 助理。請根據以下提供的資料來回答使用者的問題。

1.  **[相關歷史對話]**: 用它來理解問題的上下文，維持對話的連貫性。

如果提供的資料都無法回答，請告知使用者你找不到相關資訊。
在你的最終答案前，你可以使用 <think>...</think> 標籤來寫下你的思考過程，這部分將會被前端介面自動摺疊。

---
[相關歷史對話]:
{history_context}
---

[使用者當前問題]: {question}

你的回答:''',
            input_variables=["history_context", "question"]
        )

        self.summarizer_prompt = PromptTemplate(
            template="請將以下提供的文字內容總結成一段簡潔、流暢的摘要，保留其核心資訊。文字內容如下：\n\n---\n{text_to_summarize}\n---\n\n摘要:",
            input_variables=["text_to_summarize"]
        )

    def _get_retriever_for_user(self, user_id: str):
        return self.vector_db.as_retriever(
            search_kwargs={'k': 3, 'filter': {'user_id': user_id}})

    def set_llm_model(self, model_name: str):
        print(f"\n🔄 正在切換 LLM 模型至: {model_name}")
        try:
            self.llm = OllamaLLM(
                model=model_name, base_url=self.ollama_base_url)
            self.llm.invoke("Hi", stop=["Hi"])
            self.current_llm_model = model_name
            print(f"✅ LLM 模型成功切換為: {self.current_llm_model}")
            return True
        except Exception as e:
            print(f"❌ 切換 LLM 模型失敗: {e}")
            return False

    def set_history_retrieval(self, enabled: bool):
        print(f"🔄 將歷史對話檢索設定為: {'啟用' if enabled else '停用'}")
        self.use_history = enabled
        return True

    def add_document(self, file_path: str, user_id: str = "global"):
        print(f"📄 正在為使用者 '{user_id}' 處理新文件: {file_path}")
        loader = UnstructuredFileLoader(file_path)
        docs = loader.load()

        for doc in docs:
            doc.metadata['user_id'] = user_id

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)

        self.vector_db.add_documents(splits)
        print(
            f"✅ 文件 '{os.path.basename(file_path)}' 已成功為使用者 '{user_id}' 加入資料庫。")

        if os.path.exists(file_path):
            os.remove(file_path)

    def _summarize_text(self, text: str) -> str:
        print(f"📝 (內部) 正在總結文字，原始長度: {len(text)}")
        try:
            prompt_value = self.summarizer_prompt.format(
                text_to_summarize=text)
            summary = self.llm.invoke(prompt_value)
            print(f"✅ (內部) 總結完成，新長度: {len(summary)}")
            return summary
        except Exception as e:
            print(f"❌ (內部) 總結時發生錯誤: {e}")
            return text[:self.history_summary_threshold]

    def ask(self, question: str, user_id: str, stream: bool = False):
        print(f"\n🤔 收到來自使用者 '{user_id}' 的請求，問題: '{question}' (流式: {stream})")

        history_context = "歷史對話檢索已停用"
        retrieved_docs = []
        if self.use_history:
            print(f"🔍 (內部) 正在為使用者 {user_id} 檢索歷史對話...")
            user_retriever = self._get_retriever_for_user(user_id)
            retrieved_docs = user_retriever.get_relevant_documents(question)

            if not retrieved_docs:
                history_context = "無相關歷史對話"
            else:
                context_from_docs = "\n---\n".join(
                    [doc.page_content for doc in retrieved_docs])
                if len(context_from_docs) > self.history_summary_threshold:
                    print(
                        f"ⓘ (內部) 歷史對話過長 ({len(context_from_docs)} 字元)，正在進行總結...")
                    history_context = self._summarize_text(context_from_docs)
                else:
                    history_context = context_from_docs
        else:
            print("ⓘ (內部) 歷史對話檢索已停用。")

        print("📝 正在組合 Prompt...")
        formatted_prompt = self.main_prompt.format(
            history_context=history_context,
            question=question
        )

        if stream:
            return self.stream_and_save(question, formatted_prompt, retrieved_docs, user_id)
        else:
            try:
                full_llm_output = self.llm.invoke(formatted_prompt)
                print(f"   -> LLM 原始輸出:\n{full_llm_output}")
                think_pattern = r"<think>.*?</think>"
                final_answer = re.sub(
                    think_pattern, "", full_llm_output, flags=re.DOTALL).strip()
                self.save_qa(question, full_llm_output, user_id)
                return final_answer
            except Exception as e:
                error_msg = f"抱歉，處理您的請求時發生錯誤: {e}"
                print(f"❌ 在非串流生成過程中發生錯誤: {e}")
                return error_msg

    def stream_and_save(self, question, prompt, source_documents, user_id):
        full_answer = ""
        try:
            if source_documents:
                source_data = [
                    {
                        "page_content": doc.page_content,
                        "metadata": doc.metadata
                    }
                    for doc in source_documents
                ]
                yield f"data: {json.dumps({'type': 'sources', 'data': source_data})}"

            for chunk in self.llm.stream(prompt):
                full_answer += chunk
                response_chunk = {"type": "content",
                                  "content": chunk, "error": None}
                yield f"data: {json.dumps(response_chunk)}"

            print(f"💾 正在為使用者 {user_id} 儲存本次問答...")
            self.save_qa(question, full_answer, user_id)

        except Exception as e:
            error_msg = f"抱歉，處理您的請求時發生錯誤: {e}"
            print(f"❌ 在串流生成過程中發生錯誤: {e}")
            response_chunk = {"type": "error", "error": error_msg}
            yield f"data: {json.dumps(response_chunk)}"

        finally:
            yield f"data: [DONE]\n"

    def save_qa(self, question, answer, user_id):
        if not answer or answer.strip() == "":
            print("   -> 偵測到空回答，跳過儲存。")
            return

        qa_pair_content = f"問題: {question}\n回答: {answer}"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = {"source": "conversation",
                    "timestamp": current_time, "user_id": user_id}
        new_doc = Document(page_content=qa_pair_content, metadata=metadata)
        self.vector_db.add_documents([new_doc])
        print(f"   -> 使用者 {user_id} 的對話歷史儲存完畢！")
