# llm-evidence-gathering

Measures whether ChatGPT and Perplexity cite Gannett articles when asked about them. For each article, the pipeline asks both chatbots a question built from the headline, then records the answer, the cited sources and the pages the chatbot retrieved.

> **Before you start: set up each account by hand once.** For every Google account you put in `accounts.toml`, sign in to ChatGPT and to Perplexity in a normal browser, create the account if asked, and click through every new-user screen (welcome tours, onboarding questions, feature announcements, cookie banner). The scraper only handles the screens it knows; an unexpected onboarding page can cover the chat box and make every article fail.

## Layout

| Folder | Contents |
|---|---|
| `scraper/` | Browser scrapers for ChatGPT and Perplexity, account logins, and the parallel queue runner |
| `ingest/` | Inputs: Gannett Content API export (`Gannett_API.py`), prompt generation (`Prompt_Generator.py`), sample API queries and a sample dataset |
| `analysis/` | `Analysis_Metrics.py` and the baseline-graphs notebook |
| `tools/` | `make_test_input.py` builds a small test input; `capture_page_samples.py` saves page snapshots for debugging selectors |
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

## Testing the parallel run

A walkthrough to check the whole pipeline on a handful of articles: logins, parallel workers, retries, crash recovery and resume. It needs no Gannett API key. Plan on about 15 minutes.

### 1. Prepare accounts

Add accounts to `accounts.toml`. Each needs to be a Google account, set up by hand first (see "Before you start" at the top); both sites log in with "Continue with Google". Accounts without two-step verification work best. Passkeys are handled automatically.

How many accounts:

| Accounts | What you can test |
|---|---|
| 1 | Everything except parallelism: one worker runs the articles one after another; retries, crash recovery and resume all work |
| 1, plus `--guest-workers 1` | ChatGPT only: one logged-in and one logged-out worker in parallel (Perplexity refuses logged-out use) |
| 2 or more | Parallel runs on both sites |

```
python -m scraper.chatgpt_scraper --login-all
python -m scraper.perplexity_scraper --login-all
```

Each account logs in once per site and the session is saved under `profiles/<account>/<site>/`. Expect about 40 to 60 seconds per login. If Google asks for a phone confirmation or a code, a browser window opens; finish the step there and press Enter in the terminal.

### 2. Build a small test input

```
python tools/make_test_input.py --name partest --n 6
```

This writes `data/gannett_API_data_partest.csv` with 6 articles from `ingest/dataset.csv`. Use `--seed` to get different articles.

### 3. Run in parallel

```
python -m scraper.run_queue --model chatgpt --dates partest
```

One worker starts per account, 15 seconds apart. Worker names are `w<number>-<account>`. Progress prints every 20 seconds (example with two accounts):

```
started w1-acct1 (pid 19840) -> data/logs_chatgpt_partest/w1-acct1.log
started w2-acct2 (pid 19902) -> data/logs_chatgpt_partest/w2-acct2.log
18:01:42 {'pending': 4, 'running': 2, 'done': 0, 'failed': 0} | 20s
...
Done in 160s | {'pending': 0, 'running': 0, 'done': 6, 'failed': 0} | attempts=6
```

Expected: every task ends as `done`, about 20 to 30 seconds per article plus a 20 to 30 second pause between articles per worker. Each worker's log in `data/logs_chatgpt_partest/` shows which articles it took and how many citations and search results it found.

Without `OPENAI_API_KEY` the run prints "PromptGenerator unavailable" and uses the template "What can you tell me about: <headline>". That is fine for testing.

Both sites can run at the same time in two terminals; each account uses a separate browser profile per site.

```
python -m scraper.run_queue --model perplexity --dates partest
```

### 4. Test crash recovery

Start a new run under a different name, and while a worker is busy, kill it from a second terminal:

```
python tools/make_test_input.py --name killtest --n 4
python -m scraper.run_queue --model chatgpt --dates killtest
# second terminal, once a worker log shows it working on a task
# (use a worker name from the "started ..." lines, e.g. w2-acct2):
pkill -9 -f "worker-id w2-acct2"
```

Expected within about 20 seconds: `w2-acct2 exited with -9; released 1 task(s); restart 1`. This works with a single account too; kill `w1-<account>`. The restarted worker re-runs the interrupted article and the run still ends with every task `done`.

### 5. Test resume and retry

Run the same command again:

```
python -m scraper.run_queue --model chatgpt --dates killtest
```

Expected: `Nothing to do.` Finished articles are never re-run. If a run ends with failed tasks, `--retry-failed` puts them back in the queue.

Failed attempts retry automatically: up to 3 tries per article, 2 minutes apart, possibly on another worker. Every attempt, failed or not, is a row in `data/gannett_chatgpt_<dates>_raw.csv`; error screenshots go to `data/screenshots_chatgpt_<dates>/Errors/`.

### 6. Start a test over

```
rm -rf data/queue_chatgpt_partest.db data/queue_chatgpt_partest.db-wal data/queue_chatgpt_partest.db-shm \
       data/logs_chatgpt_partest data/screenshots_chatgpt_partest \
       data/gannett_chatgpt_partest.csv data/gannett_chatgpt_partest_raw.csv
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot connect to chrome` or a profile seems locked | A browser from an earlier login or run is still open on that profile. Close it, or stop the earlier command with Ctrl+C. |
| `login_challenge` in a worker log, worker stops | Google wants a manual step. Run `python -m scraper.<site>_scraper --login --profile <account>`, finish it in the browser, then re-run the queue command. |
| `Google rejected the email or password` | Check that account in `accounts.toml`. |
| `web search item disabled; reloading` in a ChatGPT log | Normal; ChatGPT sometimes loads the menu late. The worker reloads and continues. |
| Tasks keep failing with the same error | Look at the screenshots in `data/screenshots_<site>_<dates>/Errors/`; the site layout may have changed. `python tools/capture_page_samples.py <site> --profile <account>` saves the current page for debugging. |

## Output columns

| Column | Meaning |
|---|---|
| `response_citations` | Sources cited in the answer (JSON list) |
| `response_search_results` | Pages the chatbot retrieved, cited or not (JSON list) |
| `n_citations`, `n_search_results`, `n_search_results_not_cited` | Counts of the above |
| `search_results_status` | `ok`, `none`, `partial (x/N)` or `capture_failed` |
| `original_in_citations`, `original_in_search_results` | 1 if the article's own URL appears |
| `republisher_in_citations`, `republisher_in_search_results` | 1 if another site with a near-identical headline appears (provisional rule) |
