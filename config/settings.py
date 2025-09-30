# config/settings.py - 환경 설정
import os
from dotenv import load_dotenv

load_dotenv()

# 서버 설정
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8080))

# LLM 설정
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 로그 레벨
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")