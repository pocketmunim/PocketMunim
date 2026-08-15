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