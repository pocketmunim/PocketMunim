import os
import json
import asyncio
from groq import AsyncGroq


async def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> str:
    """Fully Asynchronous Groq Execution"""
    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GROQ_API_KEY")
    if single_key and single_key.strip() not in groq_keys:
        groq_keys.append(single_key.strip())

    all_errors = []
    for idx, key in enumerate(groq_keys):
        try:
            client = AsyncGroq(api_key=key)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            kwargs = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 4096  # 🚀 THIS IS THE FIX: Expands output capacity by 4x
            }
            if is_json:
                kwargs["response_format"] = {"type": "json_object"}

            # Non-blocking async execution
            completion = await client.chat.completions.create(**kwargs)
            return completion.choices[0].message.content.strip()
        except Exception as e:
            error_msg = f"Key #{idx + 1} [{key}] failed: {str(e)}"
            all_errors.append(error_msg)
            print(error_msg)
            continue

    error_summary = "CRITICAL: All Groq API keys failed. Error Trace:\n" + "\n".join(all_errors)
    print(error_summary)
    raise Exception("All AI API keys are currently rate-limited or invalid.")