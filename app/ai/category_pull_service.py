import os
import json
from groq import Groq
from pydantic import BaseModel, Field
from typing import Optional


class AICategoryResponse(BaseModel):
    category: Optional[str] = None
    subcategory: Optional[str] = None
    item: Optional[str] = None


class CategoryPullService:
    def __init__(self, ai_client: Groq, db_client=None):
        self.ai = ai_client
        self.db = db_client

    def _fetch_user_taxonomy(self, user_id: str) -> str:
        """
        Queries the user's relational `categories` table to build
        the active taxonomy tree for the prompt injection.
        """
        default_taxonomy = (
            "- Food & Dining: Food Delivery, Groceries, Restaurants, Cafes\n"
            "- Transportation: Fuel, Public Transport, Cab, Maintenance\n"
            "- Utilities: Electricity, Water, Internet, Mobile, Gas\n"
            "- Shopping: Clothing, Electronics, Home & Living, Personal Care\n"
            "- Entertainment: Movies, Subscriptions, Events, Gaming\n"
            "- Health & Fitness: Pharmacy, Doctor, Gym, Medical\n"
            "- Finance: Investments, Bank Fees, Insurance, Taxes\n"
            "- Income: Salary, Freelance, Dividends, Gifts"
        )

        if not self.db or not user_id:
            return default_taxonomy

        try:
            response = self.db.table('categories').select('*').eq('user_id', user_id).execute()
            rows = response.data or []
            if not rows:
                return default_taxonomy

            # Format rows into a clean readable taxonomy string for the LLM
            taxonomy_lines = []
            category_map = {row['id']: row for row in rows}

            # Group by top-level category
            top_cats = [r for r in rows if r.get('level') == 'CATEGORY']
            for cat in top_cats:
                cat_name = cat.get('name')
                sub_cats = [r for r in rows if r.get('level') == 'SUBCATEGORY' and r.get('parent_id') == cat.get('id')]
                sub_names = [s.get('name') for s in sub_cats]

                if sub_names:
                    taxonomy_lines.append(f"- {cat_name}: {', '.join(sub_names)}")
                else:
                    taxonomy_lines.append(f"- {cat_name}")

            return "\n".join(taxonomy_lines) if taxonomy_lines else default_taxonomy
        except Exception:
            return default_taxonomy

    def classify_item(self, item_name: str, user_id: str = None) -> dict:
        """
        Classifies an item using your exact enterprise taxonomy prompt.
        """
        if not self.ai:
            return {"category": None, "subcategory": None, "item": item_name}

        # Fetch dynamic taxonomy for this specific user
        taxonomy_string = self._fetch_user_taxonomy(user_id)

        # Inject taxonomy into your exact prompt template
        system_prompt = f"""You are the PocketMunim Category Classification Engine.

Your sole responsibility is to classify a given financial transaction item into the most appropriate PocketMunim Category and Subcategory.

INPUT:
- item: The transaction description or item provided by the user.

CLASSIFICATION RULES:
1. Understand the actual financial meaning and context of the item.
2. Select the most appropriate Category and the most specific applicable Subcategory.
3. Use ONLY the PocketMunim categories and subcategories supplied to you in the AVAILABLE TAXONOMY.
4. NEVER invent, rename, modify, merge, or create a new Category or Subcategory.
5. The returned Category and Subcategory MUST exactly match the spelling and capitalization of values in the AVAILABLE TAXONOMY.
6. If multiple classifications are possible, select the one that best represents the primary purpose of the transaction.
7. If the item is ambiguous, insufficient, unrelated to personal finance, or cannot be confidently classified using the AVAILABLE TAXONOMY, return null for both category and subcategory.
8. Do not make assumptions that are not reasonably supported by the item description.
9. Preserve the input item exactly as provided. Do not correct, translate, shorten, or modify it.
10. Do not include explanations, reasoning, confidence scores, recommendations, or additional fields in the response.
11. Return ONLY valid JSON.
12. Never wrap the JSON in Markdown code fences.
13. Never return additional text before or after the JSON.

AVAILABLE TAXONOMY:
{taxonomy_string}

OUTPUT FORMAT:
{{
  "category": "string or null",
  "subcategory": "string or null",
  "item": "original item exactly as provided"
}}

EXAMPLES:
Input:
item: "Swiggy dinner"
Output:
{{
  "category": "Food & Dining",
  "subcategory": "Food Delivery",
  "item": "Swiggy dinner"
}}

Input:
item: "petrol for car"
Output:
{{
  "category": "Transportation",
  "subcategory": "Fuel",
  "item": "petrol for car"
}}

Input:
item: "xyzabc123"
Output:
{{
  "category": null,
  "subcategory": null,
  "item": "xyzabc123"
}}

FINAL REQUIREMENT:
The response MUST be a single valid JSON object with exactly these three fields. If classification is not possible, category and subcategory MUST be null."""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"item: \"{item_name}\""}
                ],
                temperature=0.0
            )
            raw_content = completion.choices[0].message.content.strip()

            # Clean potential markdown wrappers just in case the model hallucinates them
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            validated = AICategoryResponse(**parsed)

            return {
                "category": validated.category,
                "subcategory": validated.subcategory,
                "item": validated.item or item_name
            }
        except Exception:
            return {"category": None, "subcategory": None, "item": item_name}