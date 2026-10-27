"""
scraper/worker.py
---------
One queue worker: one browser, one account (or guest), pulls tasks until the queue
is empty. Started by scraper/run_queue.py; can also be run by hand for debugging:

    python -m scraper.worker --db data/2026-10-20/chatgpt/queue.db --model chatgpt --dates 2026-10-20 \
        --worker-id w1 --account acct1

Loop (PRD 5.2): claim -> throttle -> run_one -> classify -> record -> repeat.
"""

from __future__ import annotations

import argparse
import importlib
import random
import sys
import time
from pathlib import Path

from . import paths
from . import queue_db as q
from .scraper_base import (ROOT, BadInputError, BlockedError, LoginChallenge, RetryableError,
                          ScraperError, found_source, source_flags)

SCRAPERS = {
    "chatgpt": ("chatgpt_scraper", "ChatGPTScraper"),
    "perplexity": ("perplexity_scraper", "PerplexityScraper"),
}


def log(worker_id: str, msg: str):
    print(f"{time.strftime('%H:%M:%S')} [{worker_id}] {msg}", flush=True)


def make_scraper(model: str, account: str | None, headless: bool):
    mod, cls = SCRAPERS[model]
    module = importlib.import_module(f"scraper.{mod}")
    return getattr(module, cls)(headless=headless, profile=account)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--model", required=True, choices=sorted(SCRAPERS))
    p.add_argument("--dates", default="run")
    p.add_argument("--worker-id", required=True)
    p.add_argument("--account", help="account name from accounts.toml; omit for guest")
    p.add_argument("--headful", action="store_true")
    p.add_argument("--max-tries", type=int, default=3)
    p.add_argument("--retry-cooldown", type=float, default=120)
    p.add_argument("--blocked-cooldown", type=float, default=300, help="wait before a blocked task is tried again")
    p.add_argument("--blocked-cap", type=int, default=3, help="mark a task failed after this many blocks")
    p.add_argument("--idle-poll", type=float, default=15)
    a = p.parse_args()

    wid, acct = a.worker_id, a.account
    acct_label = acct or "guest"
    con = q.connect(a.db)
    shots = paths.screenshots_dir(a.dates, a.model)
    (shots / "Errors").mkdir(parents=True, exist_ok=True)

    scraper = None

    def restart():
        nonlocal scraper
        if scraper is not None:
            scraper.close()
        scraper = make_scraper(a.model, acct, headless=not a.headful)

    log(wid, f"start | model={a.model} account={acct or 'guest'}")
    restart()
    try:
        while True:
            task = q.claim(con, wid)
            if task is None:
                if q.open_work(con) == 0:
                    log(wid, "queue empty; exiting")
                    return 0
                time.sleep(a.idle_poll)
                continue

            tid = task["id"]
            log(wid, f"task {tid} (try {task['tries'] + 1}): {str(task['headline'])[:70]}")
            time.sleep(random.uniform(*scraper.throttle))
            q.heartbeat(con, tid, wid)
            started = time.time()
            try:
                if not (task.get("prompt") or "").strip() or not (task.get("headline") or "").strip():
                    raise BadInputError("empty headline or prompt")
                res = scraper.run_one(task["prompt"])
                q.heartbeat(con, tid, wid)
                flags = source_flags(a.model, res, task["article_url"], task["headline"])
                if found_source(flags):
                    res.screenshot_path = scraper.screenshot(shots / f"Task_{tid}_a{task['tries'] + 1}_SourceUsed.png")
                row = {**res.to_row(), **flags}
                orig = flags.get("original_in_sources", flags["original_in_citations"] or flags["original_in_search_results"])
                repub = flags["republisher_in_citations"] or flags["republisher_in_search_results"]
                q.record_attempt(con, task, wid, acct_label, "done", started, row)
                q.finish(con, tid, wid, "done")
                log(wid, f"task {tid} done in {time.time() - started:.0f}s | citations={row['n_citations']} "
                         f"search={row['n_search_results']} original={orig} republisher={repub}")

            except BadInputError as e:
                q.record_attempt(con, task, wid, acct_label, "bad_input", started, error_class=e.kind, error_message=str(e))
                q.finish(con, tid, wid, "failed", f"bad_input: {e}")
                log(wid, f"task {tid} failed: bad input")

            except LoginChallenge as e:
                shot = scraper.screenshot(shots / "Errors" / f"Task_{tid}_a{task['tries'] + 1}_login.png")
                q.record_attempt(con, task, wid, acct_label, "blocked", started, error_class=e.kind,
                                 error_message=str(e), screenshot_path=shot)
                q.give_back(con, tid, wid, f"login_challenge: {e}")
                log(wid, f"login needs a person; this worker stops. {e}")
                return 3

            except BlockedError as e:
                shot = scraper.screenshot(shots / "Errors" / f"Task_{tid}_a{task['tries'] + 1}_blocked.png")
                q.record_attempt(con, task, wid, acct_label, "blocked", started, error_class=e.kind,
                                 error_message=str(e), screenshot_path=shot)
                status = q.give_back(con, tid, wid, f"blocked: {e}", cap=a.blocked_cap, cooldown=a.blocked_cooldown)
                log(wid, f"task {tid} blocked ({e}) -> {status}; back in the queue after {a.blocked_cooldown:.0f}s")
                restart()

            except (RetryableError, ScraperError) as e:
                shot = scraper.screenshot(shots / "Errors" / f"Task_{tid}_a{task['tries'] + 1}_retryable.png")
                q.record_attempt(con, task, wid, acct_label, "retryable", started, error_class=e.kind,
                                 error_message=str(e), screenshot_path=shot)
                status = q.retry_later(con, tid, wid, a.retry_cooldown, a.max_tries, f"{e.kind}: {e}")
                log(wid, f"task {tid} {e.kind}: {str(e)[:100]} -> {status}")
                restart()

            except Exception as e:               # browser crash or bug: treat as retryable
                q.record_attempt(con, task, wid, acct_label, "retryable", started,
                                 error_class=type(e).__name__, error_message=str(e))
                status = q.retry_later(con, tid, wid, a.retry_cooldown, a.max_tries, f"{type(e).__name__}: {e}")
                log(wid, f"task {tid} unexpected {type(e).__name__}: {str(e)[:100]} -> {status}")
                restart()
    except KeyboardInterrupt:
        log(wid, "interrupted")
        return 130
    finally:
        if scraper is not None:
            scraper.close()


if __name__ == "__main__":
    sys.exit(main())
