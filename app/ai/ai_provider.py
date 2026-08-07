import os
import json
import asyncio
from groq import AsyncGroq


async def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> tuple[
    str, str]:
    """Fully Asynchronous Groq Execution returning (content, finish_reason)"""
    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GROQ_API_KEY")
    if single_key and single_key.strip() not in groq_keys:
        groq_keys.append(single_key.strip())

    if not groq_keys:
        raise Exception("No Groq API keys configured in environment variables.")

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
                "temperature": 0.0
            }
            if is_json:
                kwargs["response_format"] = {"type": "json_object"}

            completion = await client.chat.completions.create(**kwargs)
            # RETURN BOTH THE CONTENT AND THE FINISH REASON
            return completion.choices[0].message.content.strip(), completion.choices[0].finish_reason
        except Exception as e:
            # Mask the actual key string for security, but keep the exact error
            error_msg = f"Groq Error (Key {idx + 1}): {str(e)}"
            all_errors.append(error_msg)
            print(error_msg)
            continue

    # 🚀 EXPOSE EXACT GROQ ERROR TO TELEGRAM
    error_summary = " | ".join(all_errors)
    raise Exception(f"AI Provider Failed: {error_summary}")