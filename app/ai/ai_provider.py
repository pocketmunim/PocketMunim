import os
import json
import asyncio
from groq import AsyncGroq


async def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> tuple[
    str, str]:
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
            return completion.choices[0].message.content.strip(), completion.choices[0].finish_reason
        except Exception as e:
            error_msg = f"Groq Key {idx + 1} Failure: {str(e)}"
            all_errors.append(error_msg)
            print(error_msg)
            continue

    error_summary = " | ".join(all_errors)
    raise Exception(f"AI Resilient Provider Exhausted: {error_summary}")


class AsyncAIProvider:
    """
    Adapter class to wrap the existing resilient AI function for the new DI container.
    """

    async def extract_transaction(self, text: str):
        # Base system prompt to enforce the JSON schema expected by the router
        system_prompt = (
            "You are a strict financial parser. Extract the transaction details from the user's text. "
            "Respond ONLY with a valid JSON object containing the keys: 'amount' (float) and 'category' (string)."
        )

        # Call the protected core function
        response_json, _ = await execute_resilient_ai(system_prompt, text, is_json=True)

        # Parse the JSON
        data = json.loads(response_json)

        # Create a dynamic object to support the dot-notation (extraction.amount) used in router.py
        class ExtractionResult:
            def __init__(self, d):
                self.amount = float(d.get('amount', 0.0))
                self.category = str(d.get('category', 'Uncategorized'))
                self.date = str(d.get('date', 'Today'))

        return ExtractionResult(data)