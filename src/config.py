import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables from .env file if present
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings(BaseModel):
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    github_access_token: str = os.getenv("GITHUB_ACCESS_TOKEN", "")
    whatsapp_token: str = os.getenv("WHATSAPP_TOKEN", "")
    whatsapp_phone_id: str = os.getenv("WHATSAPP_PHONE_ID", "")
    my_phone_number: str = os.getenv("MY_PHONE_NUMBER", "")
    
    database_path: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "watchdog.db"))
    stack_context_path: str = os.getenv("STACK_CONTEXT_PATH", str(BASE_DIR / "stack_context.json"))
    port: int = int(os.getenv("PORT", "8000"))
    env: str = os.getenv("ENV", "development")

settings = Settings()
