"""
Prompt_Generator.py
-------------------
Generates natural-language search prompts from article headlines and keywords
by calling the OpenAI Chat Completions API (gpt-4o-mini by default).

The generated prompt is used as the actual query sent to AI chatbots
(ChatGPT, Claude, Perplexity) instead of the hardcoded
  'Tell me about "{headline}"'
template. This produces more varied, realistic queries that better reflect
how real users would search for the same story.

Usage:
    from Prompt_Generator import PromptGenerator

    pg = PromptGenerator()                     # reads OPENAI_API_KEY from env
    prompt = pg.generate(row["headline"], row["keywords"])
"""

import os
import re
import keyring
import Set_Password
from openai import OpenAI


class PromptGenerator:
    # System prompt that instructs the LLM how to craft the search query.
    # Keep it tightly scoped so the output is a single sentence.
    SYSTEM_PROMPT = (
        "You are a helpful assistant that converts news article metadata "
        "into a single, natural-sounding search query — the kind a curious "
        "person would type into an AI chatbot to learn about the story. "
        "Rules:\n"
        "- Output ONLY the query, no quotes, no labels, no explanation.\n"
        "- One sentence or short phrase, 10–25 words.\n"
        "- Sound like a real user, not a headline.\n"
        "- Do NOT start with 'Tell me about'.\n"
        "- Incorporate the most newsworthy keywords naturally."
    )

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None):
        """
        Parameters
        ----------
        model:   OpenAI model to use for prompt generation. gpt-4o-mini is
                 fast and cheap — ideal for batch preprocessing.
        api_key: Optional API key. If None, falls back to the OPENAI_API_KEY
                 environment variable, then the system keyring.
        """
        self.model = model
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY") or self._get_key_from_keyring()
        if not resolved_key:
            raise ValueError(
                "No OpenAI API key found. Set the OPENAI_API_KEY environment "
                "variable, pass api_key= to PromptGenerator(), or store it "
                "with Set_Password.py under service name 'openai'."
            )
        self.client = OpenAI(api_key=resolved_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, headline: str, keywords: str = "", fallback: bool = True) -> str:
        """
        Generate a natural search prompt for one article.

        Parameters
        ----------
        headline:  Article headline string.
        keywords:  Comma-separated keywords string from the API data.
                   Pass an empty string if the column is NaN / missing.
        fallback:  If True and the API call fails, return a safe default
                   prompt so the scraper can continue rather than crashing.

        Returns
        -------
        A natural-language query string ready to paste into a chatbot.
        """
        headline = str(headline).strip()
        keywords_clean = self._clean_keywords(str(keywords))

        user_message = self._build_user_message(headline, keywords_clean)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=80,
                temperature=0.7,
            )
            prompt = response.choices[0].message.content.strip()
            # Strip any stray surrounding quotes the model might add
            prompt = prompt.strip('"').strip("'")
            return prompt

        except Exception as e:
            print(f"[PromptGenerator] API call failed: {e}")
            if fallback:
                return self._fallback_prompt(headline)
            raise

    def generate_batch(self, rows, headline_col: str = "headline",
                       keywords_col: str = "keywords") -> list[str]:
        """
        Convenience method: generate prompts for every row in an iterable
        of dicts / DataFrame rows.

        Returns a list of prompt strings in the same order.
        """
        prompts = []
        for row in rows:
            headline = row.get(headline_col, "")
            keywords = row.get(keywords_col, "") or ""
            prompts.append(self.generate(headline, keywords))
        return prompts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_keywords(raw: str) -> str:
        """
        Trim the keywords string to the most useful first N entries and
        drop internal noise like sentiment labels ('Overall Negative',
        'Life NOW', category codes, etc.).
        """
        if not raw or raw.lower() == "nan":
            return ""

        # Split on comma, strip whitespace
        parts = [k.strip() for k in raw.split(",") if k.strip()]

        # Remove generic editorial/sentiment labels that add no search value
        noise_patterns = re.compile(
            r"^(overall (positive|negative|neutral)|life now|campaigns|"
            r"people & society|celebrities|breaking news|top stories|"
            r"news|politics|sports|entertainment).*$",
            re.IGNORECASE,
        )
        parts = [p for p in parts if not noise_patterns.match(p)]

        # Keep first 6 meaningful keywords to stay concise
        return ", ".join(parts[:6])

    @staticmethod
    def _build_user_message(headline: str, keywords: str) -> str:
        msg = f'Headline: {headline}'
        if keywords:
            msg += f'\nKey topics: {keywords}'
        msg += (
            "\n\nWrite a single natural search query someone would ask an AI "
            "chatbot to learn about this news story."
        )
        return msg

    @staticmethod
    def _fallback_prompt(headline: str) -> str:
        """Last-resort prompt if the API is unavailable."""
        return f'What can you tell me about: {headline}'

    @staticmethod
    def _get_key_from_keyring() -> str | None:
        """Try to retrieve the OpenAI API key from the system keyring."""
        try:
            return keyring.get_password("openai", "api_key")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# CLI convenience: run directly to test a single generation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    headline_arg = sys.argv[1] if len(sys.argv) > 1 else "Omarosa slams Trump's 'Black jobs' debate comments"
    keywords_arg = sys.argv[2] if len(sys.argv) > 2 else "Omarosa Manigault Newman,Donald Trump,African Americans"

    pg = PromptGenerator()
    result = pg.generate(headline_arg, keywords_arg)
    print(f"Generated prompt: {result}")
