# history/

Deprecated code, kept for reference. Nothing in the current pipeline imports these files.

| File | Replaced by |
|---|---|
| `ChatGPT_Scraper.py` | `scraper/chatgpt_scraper.py` (guest and logged-in pages, Web search on, search results from the conversation response) |
| `perplexity_scraper.py` | `scraper/perplexity_scraper.py` (logged-in, full source list) |
| `Chatbot_Scraper.py` | `scraper/scraper_base.py` (shared base, typed errors, completion check) |
| `Claude_Scraper.py` | not replaced; Claude is out of scope |
| `Set_Password.py` | `accounts.toml` (see `accounts.example.toml`) for site logins; the OpenAI key comes from `OPENAI_API_KEY` or the keyring |

The selectors in the old scrapers no longer match the live ChatGPT and Perplexity pages (checked 2026-10-25).
