import os
from dotenv import load_dotenv
from typing import List

load_dotenv()

class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    GROQ_API_KEYS_RAW: str = os.getenv("GROQ_API_KEYS", "")
    QSTASH_TOKEN: str = os.getenv("QSTASH_TOKEN", "")
    MASTER_PEPPER: str = os.getenv("APP_MASTER_PEPPER", "0x_ISHITA_CORE_QUANTUM_PEPPER_99283_SECURE")

    @property
    def groq_keys(self) -> List[str]:
        if not self.GROQ_API_KEYS_RAW:
            return []
        return [k.strip() for k in self.GROQ_API_KEYS_RAW.split(",") if k.strip()]

settings = Settings()
