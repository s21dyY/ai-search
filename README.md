# AI Search

This project collects Gannett articles, queries ChatGPT, Claude, and Perplexity
through browser automation, and measures similarity and source citations.
`sesame_lc_01.ipynb` separately explores BigQuery/Search Console data.

## Local setup

Use **Python 3.12**. `Gannett_API.py` uses f-string syntax that requires Python
3.12 or newer, while the pinned `blis==1.2.0` requires Python older than 3.13.
The existing requirements include macOS-specific PyObjC packages.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

The local environment is `.venv/`. Select `.venv/bin/python` as the interpreter
in your IDE. Run scripts from the repository root so relative data paths work.

For Jupyter, register and select the project kernel:

```sh
python -m ipykernel install --user --name ai-search --display-name "AI Search (Python 3.12)"
```

## Runtime configuration

- Install Google Chrome for the SeleniumBase scrapers. SeleniumBase manages
  the browser driver; it may download a matching driver on first use.
- Prompt generation uses Gemini; see the local test setup below.
- ChatGPT and Perplexity start without account sign-in. A website may require
  an account before answering. ChatGPT's previous login
  calls remain commented out; restore both to use `Set_Password.py` and the system keyring.
  Guest citation URLs may be unavailable even when an answer is collected.
  ChatGPT writes successful source results as JSON lists in `response_citations`
  and `response_search_results`. Unavailable sections or extraction failures are
  recorded as readable `ERROR: ...` messages in the affected column; their match
  flags remain unset. A successfully read empty section is stored as `[]`.
  On the guest interface, `response_search_results` captures the search-activity
  result list from the normal response stream before the UI hides it. This list
  may overlap with citations; it is not limited to uncited links.
  Guest citations use the same stream's citation records, with the previous
  source-card extraction retained as a fallback.
  Perplexity records `collection_status` as `complete`, `partial`, or `account_required`;
  inline citation links are retained when its full Sources panel is blocked.
- `Gannett_API.py` currently has an empty API key and an author-specific output
  path. Configure these before fetching articles.
- Scrapers read `data/gannett_API_data_<dates>.csv`. The `data/` directory and
  the selected article input must exist before scraping.
- Set `input_path` in `Analysis_Metrics.py` to an existing scraper output CSV;
  this script reads data and writes summaries immediately when executed.
- The notebook needs Google Cloud authentication, BigQuery permissions, and
  access to the referenced tables and Cloud Storage objects.

Installing dependencies does not configure these accounts or data sources.

## Gemini prompt generation

`PromptGenerator()` defaults to `gemini-3.5-flash-lite`. It uses the installed
OpenAI client against [Google's compatibility endpoint](https://ai.google.dev/gemini-api/docs/openai);
requests go to Google and use a Gemini API key. No additional SDK is needed.
All three scrapers already use `PromptGenerator()`, so they use this configuration.

1. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Create a local `.env` file and set `GEMINI_API_KEY` in it. `.env` is ignored
   by Git and is loaded from the current working directory. Run the script from
   the repository root. Keep `GEMINI_MODEL=gemini-3.5-flash-lite`
   or change it to another supported Gemini model.
3. Activate `.venv` and run a single prompt-generation test:

```sh
source .venv/bin/activate
python Prompt_Generator.py "Pittsburgh opens a new downtown transit station" "Pittsburgh, public transit"
```

The standalone call retains its original template-fallback behavior, as do
the scrapers. Use the CSV integration test below to expose API errors directly.
The request uses minimal thinking, a 256-token output limit, a 30-second timeout,
and at most one SDK retry.

Configuration precedence:

- API key: explicit `api_key=` argument, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, then
  system keyring service `gemini` / username `api_key`.
- Model: explicit `model=` argument, `GEMINI_MODEL`, then
  `gemini-3.5-flash-lite`.
- Existing environment variables take precedence over `.env` values.

`OPENAI_API_KEY` is not used for Gemini authentication.

## Three-article local test

`data/prompt_generator_test.csv` contains three distinct articles extracted from
`dataset.csv`: a book story, a local development story, and an Olympics story.
Headlines and comma-separated keywords are unchanged. `pageURL` is flattened
from its JSON wrapper; section/subsection are extracted from `classificationV2`.
The original article ID, publication timestamp, source filename, and source
record number are retained. `source_record` counts CSV records with the header
as record 1, rather than physical lines (the source contains multiline fields).
The source dataset is unchanged, and full article bodies are omitted because
the generator only consumes headline and keywords.

The sample CSV and its generated output are local-only and ignored by Git.
On a new checkout, prepare `data/prompt_generator_test.csv` from `dataset.csv`
before running this test.

Run from the repository root after configuring `.env`:

```sh
source .venv/bin/activate
python run_prompt_generator_test.py
```

This live integration test processes the input CSV with no article-count limit
and waits 20 seconds between articles. It uses the generator's configured SDK
retry behavior. Template fallback is disabled, so an unresolved API error stops
the script and displays the exception. Successful results are written to
`data/prompt_generator_test_results.csv`, including the generated query, model,
word count, and UTC timestamp. Rerunning replaces that result file and consumes
fresh API requests.

This is conservative pacing, not a guarantee of available quota. Google's
[rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits)
directs you to [AI Studio](https://aistudio.google.com/usage?timeRange=last-28-days&tab=rate-limit)
for your project's active RPM, TPM, and daily limits. Quotas are shared across
the project, so other API usage can still cause a rate-limit error.


## Tracked scraper results

Only the latest successful ChatGPT run is tracked under
`data/chatgpt_live_20_2026-10-25_121122/`. Its final CSV contains 20 articles,
119 citation entries, and 249 search-result entries. See that directory's
`RUN_REPORT.md` and `verification.json` for the validation scope.

`dataset.csv` remains tracked. Other run folders, local sample inputs, duplicate
checkpoints, logs, and driver lock files are ignored. Perplexity's account-free
batch workflow remains unverified because subsequent guest queries encountered
sign-in gates.
