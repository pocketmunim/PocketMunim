import os
import json
from groq import Groq


def log_error_to_db(db_client, error_msg: str):
    try:
        if db_client:
            db_client.table("error_logs").insert({"error_message": error_msg}).execute()
    except Exception as db_err:
        print(f"Failed to write to error_logs table: {db_err}")


def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> str:
    # 1. Gather all Groq Keys
    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GROQ_API_KEY")
    if single_key and single_key.strip() not in groq_keys:
        groq_keys.append(single_key.strip())

    last_error = None

    # 2. Try Groq Keys Sequentially
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
            continue

    # 3. Fallback to Google Gemini if all Groq keys fail
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            generation_config = {"response_mime_type": "application/json"} if is_json else {}
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                generation_config=generation_config,
                system_instruction=system_prompt
            )
            response = model.generate_content(user_prompt)
            return response.text.strip()
        except Exception as e:
            last_error = f"Gemini Fallback Error: {str(e)}"
            print(last_error)

    # 4. If all providers fail, log to server error_logs and raise
    error_summary = f"CRITICAL: All AI providers failed. Last error: {last_error}"
    print(error_summary)
    log_error_to_db(db_client, error_summary)
    raise Exception(error_summary)