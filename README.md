# llm-evidence-gathering

Measures whether ChatGPT and Perplexity cite Gannett articles when asked about them. For each article, the pipeline asks both chatbots a question built from the headline, then records the answer, the cited sources and the pages the chatbot retrieved.

## Layout

| Folder | Contents |
|---|---|
| `scraper/` | Browser scrapers for ChatGPT and Perplexity, account logins, and the parallel queue runner |
| `ingest/` | Inputs: Gannett Content API export (`Gannett_API.py`), prompt generation (`Prompt_Generator.py`), sample API queries and a sample dataset |
| `analysis/` | `Analysis_Metrics.py` and the baseline-graphs notebook |
| `tools/` | `capture_page_samples.py`, saves page snapshots for debugging selectors |
| `history/` | Deprecated scrapers, kept for reference (see `history/README.md`) |

Not in git: `accounts.toml` (credentials), `profiles/` (browser sessions), `data/` (inputs, results, logs, screenshots).

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp accounts.example.toml accounts.toml     # then fill in real accounts
export OPENAI_API_KEY=sk-...               # used to generate prompts
```

Chrome must be installed. Run every command from the repo root.

## Run

1. Export articles for a date into `data/gannett_API_data_<dates>.csv`:

   ```
   python -m ingest.Gannett_API 2026-10-20
   ```

2. Log every account in once. Logins are automatic; a visible browser opens only if Google asks for a manual step such as two-step verification:

   ```
   python -m scraper.chatgpt_scraper --login-all
   python -m scraper.perplexity_scraper --login-all
   ```

3. Run the queue. One worker per account in `accounts.toml`; failed articles are retried; re-running the same command resumes:

   ```
   python -m scraper.run_queue --model chatgpt --dates 2026-10-20
   python -m scraper.run_queue --model perplexity --dates 2026-10-20
   ```

   Useful options: `--limit N`, `--retry-failed`, `--guest-workers N` (ChatGPT only, no account).

Outputs in `data/`:

- `gannett_<model>_<dates>.csv`: one row per article
- `gannett_<model>_<dates>_raw.csv`: one row per attempt
- `logs_<model>_<dates>/`: one log per worker
- `screenshots_<model>_<dates>/`: pages where the original or a republisher was found, and error pages

## Output columns

| Column | Meaning |
|---|---|
| `response_citations` | Sources cited in the answer (JSON list) |
| `response_search_results` | Pages the chatbot retrieved, cited or not (JSON list) |
| `n_citations`, `n_search_results`, `n_search_results_not_cited` | Counts of the above |
| `search_results_status` | `ok`, `none`, `partial (x/N)` or `capture_failed` |
| `original_in_citations`, `original_in_search_results` | 1 if the article's own URL appears |
| `republisher_in_citations`, `republisher_in_search_results` | 1 if another site with a near-identical headline appears (provisional rule) |
