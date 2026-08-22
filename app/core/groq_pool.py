from groq import Groq
from app.core.config import settings
import itertools
from typing import Optional

class GroqClientPool:
    def __init__(self):
        self._keys = settings.groq_keys
        self._key_cycle = itertools.cycle(self._keys) if self._keys else None

    def get_client(self) -> Groq:
        if not self._key_cycle or not self._keys:
            raise ValueError("No GROQ_API_KEYS provisioned in environment.")
        active_key = next(self._key_cycle)
        return Groq(api_key=active_key)

groq_pool = GroqClientPool()
