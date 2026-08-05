import os
import json
from groq import Groq


def log_error_to_db(db_client, error_msg: str):
    """Logs critical AI execution failures directly to the database."""
    try:
        if db_client:
            db_client.table("error_logs").insert({"error_message": error_msg}).execute()
    except Exception as db_err:
        print(f"Failed to write to error_logs table: {db_err}")


def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> str:
    """
    Executes AI requests with built-in Groq Key Rotation.
    If a rate limit (429) or error occurs, it automatically fails over to the next available key.
    """

    # 1. Gather all Groq Keys from environment variables
    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]

    # Also check single key variable just in case
    single_key = os.getenv("GROQ_API_KEY")
    if single_key and single_key.strip() not in groq_keys:
        groq_keys.append(single_key.strip())

    last_error = None

    # 2. Try Groq Keys Sequentially (Rotation)
    for idx, key in enumerate(groq_keys):
        try:
            client = Groq(api_key=key)
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

            completion = client.chat.completions.create(**kwargs)
            return completion.choices[0].message.content.strip()

        except Exception as e:
            last_error = f"Groq Key #{idx + 1} Error: {str(e)}"
            print(last_error)
            # Instantly move to the next key on failure
            continue

    # 3. If all Groq keys fail, log to server error_logs and raise exception
    error_summary = f"CRITICAL: All Groq API keys failed or rate-limited. Last error: {last_error}"
    print(error_summary)

    # Log the failure securely to your Supabase database
    log_error_to_db(db_client, error_summary)

    raise Exception(error_summary)