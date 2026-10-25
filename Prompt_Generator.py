"""
Prompt_Generator.py
-------------------
Generates natural-language search prompts from article headlines and keywords
by calling Gemini's OpenAI-compatible API (gemini-3.5-flash-lite by default).

The generated prompt is used as the actual query sent to AI chatbots
(ChatGPT, Claude, Perplexity) instead of the hardcoded
  'Tell me about "{headline}"'
template. This produces more varied, realistic queries that better reflect
how real users would search for the same story.

Usage:
    from Prompt_Generator import PromptGenerator

    pg = PromptGenerator()                     # reads GEMINI_API_KEY from env/.env
    prompt = pg.generate(row["headline"], row["keywords"])
"""

import os
import re
import keyring
from dotenv import load_dotenv
from openai import OpenAI


class PromptGenerator:
    DEFAULT_MODEL = "gemini-3.5-flash-lite"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

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

    def __init__(self, model: str | None = None, api_key: str | None = None):
        """
        Parameters
        ----------
        model:   Gemini model override. Defaults to GEMINI_MODEL from the
                 environment or .env, then gemini-3.5-flash-lite.
        api_key: Optional Gemini API key. Otherwise reads GEMINI_API_KEY,
                 then GOOGLE_API_KEY, then keyring service 'gemini' /
                 username 'api_key'. Existing environment values take
                 precedence over the repository's .env file.
        """
        load_dotenv(".env", override=False)
        self.model = model or os.environ.get("GEMINI_MODEL") or self.DEFAULT_MODEL
        resolved_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or self._get_key_from_keyring()
        )
        if not resolved_key:
            raise ValueError("Invalid API Key.")
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=self.BASE_URL,
            timeout=30.0,
            max_retries=1,
        )

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
                max_tokens=256,
                temperature=1.0,
                extra_body={"reasoning_effort": "minimal"},
            )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise ValueError("Gemini output was truncated by the token limit.")
            prompt = (choice.message.content or "").strip()
            # Strip any stray surrounding quotes the model might add
            prompt = prompt.strip('"').strip("'").strip()
            if not prompt:
                raise ValueError("Gemini returned no prompt text.")
            return prompt

        except Exception as e:
            print(f"[PromptGenerator] Gemini API call failed: {e}")
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
        """Try to retrieve the Gemini API key from the system keyring."""
        try:
            return keyring.get_password("gemini", "api_key")
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
