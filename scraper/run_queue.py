"""
scraper/run_queue.py
------------
Parallel runner (orchestrator). Enqueues one task per article, starts one worker
process per account, keeps them alive, and exports CSVs when the queue is done.
Restarting it resumes from the queue: finished tasks are not re-run.

    python -m scraper.run_queue --model chatgpt --dates 2026-10-20
    python -m scraper.run_queue --model perplexity --dates 2026-10-20 --limit 20
    python -m scraper.run_queue --model chatgpt --dates 2026-10-20 --guest-workers 2   # no accounts

Workers = the accounts in accounts.toml that list this model (or --accounts a,b).
Input:   data/<dates>/gannett_API_data_<dates>.csv  (or --input PATH)
Output:  data/<dates>/<model>/: gannett_<model>_<dates>.csv (for the analysis),
         gannett_<model>_<dates>_raw.csv, queue.db, logs/, screenshots/
         Layout: scraper/paths.py

Design: local-docs/prd-parallel-runs-and-retries.md.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import paths
from . import queue_db as q
from .scraper_base import ROOT

DEFAULTS = {
    #                 chatgpt  perplexity
    "blocked_pause": {"chatgpt": 1800, "perplexity": 600},
}


def build_prompts(articles: list[dict], use_generator: bool = True) -> None:
    """Generate one prompt per article, once, at enqueue time (PRD 5.1)."""
    gen = None
    if use_generator:
        try:
            from ingest.Prompt_Generator import PromptGenerator
            gen = PromptGenerator()
        except Exception as e:
            print(f"PromptGenerator unavailable ({str(e)[:80]}); using the fallback template.")
    for a in articles:
        if not a["headline"].strip():
            a["prompt"], a["prompt_source"] = "", "none"
            continue
        if gen is not None:
            a["prompt"] = gen.generate(a["headline"], a.get("keywords", ""))
            a["prompt_source"] = "generated"
        else:
            a["prompt"] = f"What can you tell me about: {a['headline']}"
            a["prompt_source"] = "fallback"


class Worker:
    def __init__(self, wid: str, account: str | None, cmd: list[str], log_path: Path):
        self.wid, self.account, self.cmd, self.log_path = wid, account, cmd, log_path
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.stopped = False                 # exited on purpose (queue empty or login needs a person)

    def start(self):
        log = open(self.log_path, "a", buffering=1)
        # New session = own process group, so its Chrome children can be killed together.
        self.proc = subprocess.Popen(self.cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                     cwd=str(ROOT))

    def kill_tree(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        elif self.proc:
            try:                                 # leader exited; children (Chrome) may linger
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass


def main():
    sys.stdout.reconfigure(line_buffering=True)      # progress shows up live even when piped
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, choices=["chatgpt", "perplexity"])
    p.add_argument("--dates", required=True, help="YYYY-MM-DD[_DD]; also names the output files")
    p.add_argument("--input", help="input CSV (default data/<dates>/gannett_API_data_<dates>.csv)")
    p.add_argument("--limit", type=int, help="only the first N articles")
    p.add_argument("--accounts", help="comma-separated account names (default: all for this model)")
    p.add_argument("--guest-workers", type=int, default=0, help="extra logged-out workers (ChatGPT only)")
    p.add_argument("--headful", action="store_true")
    p.add_argument("--no-generator", action="store_true", help="use the fallback prompt template")
    p.add_argument("--stagger", type=float, default=15)
    p.add_argument("--max-tries", type=int, default=3)
    p.add_argument("--retry-cooldown", type=float, default=120)
    p.add_argument("--blocked-pause", type=float)
    p.add_argument("--stuck-after", type=float, default=600)
    p.add_argument("--stuck-cap", type=int, default=3)
    p.add_argument("--max-restarts", type=int, default=5, help="per worker")
    p.add_argument("--retry-failed", action="store_true", help="put failed tasks back in the queue first")
    a = p.parse_args()

    # --- workers ---
    from .accounts import load_accounts
    accts = load_accounts(service=a.model)
    if a.accounts:
        wanted = [x.strip() for x in a.accounts.split(",") if x.strip()]
        missing = [w for w in wanted if w not in {x.name for x in accts}]
        if missing:
            p.error(f"not in accounts.toml for {a.model}: {', '.join(missing)}")
        accts = [x for x in accts if x.name in wanted]
    if a.model == "perplexity" and a.guest_workers:
        p.error("Perplexity refuses logged-out use; use accounts")
    slots = [(f"w{i + 1}-{x.name}", x.name) for i, x in enumerate(accts)]
    slots += [(f"w{len(slots) + i + 1}-guest", None) for i in range(a.guest_workers)]
    if not slots:
        p.error(f"no workers: add accounts for {a.model} to accounts.toml or pass --guest-workers")

    # --- queue ---
    dbp = q.db_path(a.model, a.dates)
    con = q.connect(dbp)
    in_path = Path(a.input) if a.input else paths.input_csv(a.dates)
    if not in_path.exists():
        p.error(f"input not found: {paths.rel(in_path)} (run ingest/Gannett_API.py or tools/make_test_input.py)")
    articles = q.load_articles(in_path)
    import pandas as pd
    missing = [c for c in q.REQUIRED_INPUT if c not in pd.read_csv(in_path, nrows=0).columns]
    if missing:
        print(f"WARNING: input has no {', '.join(missing)} column(s); "
              f"analysis/Analysis_Metrics.py needs them (the output will have them empty).")
    if a.limit:
        articles = articles[: a.limit]
    have = q.known_urls(con)
    new = [x for x in articles if x["article_url"] not in have]
    if new:
        print(f"Generating prompts for {len(new)} new articles...")
        build_prompts(new, use_generator=not a.no_generator)
    added, existing = q.enqueue(con, a.model, new)
    if a.retry_failed:
        print(f"Re-queued {q.reset_failed(con)} failed task(s).")
    print(f"Queue {paths.rel(dbp)}: {added} added, {len(articles) - added} already queued | {q.counts(con)}")
    if q.open_work(con) == 0:
        print("Nothing to do.")
        print("Exported:", *(paths.rel(x) for x in q.export(con, a.model, a.dates)))
        return 0

    # --- start workers, staggered ---
    logs = paths.logs_dir(a.dates, a.model)
    logs.mkdir(parents=True, exist_ok=True)
    blocked_pause = a.blocked_pause if a.blocked_pause is not None else DEFAULTS["blocked_pause"][a.model]
    workers = []
    for wid, acct in slots:
        cmd = [sys.executable, "-m", "scraper.worker", "--db", str(dbp), "--model", a.model, "--dates", a.dates,
               "--worker-id", wid, "--max-tries", str(a.max_tries), "--retry-cooldown", str(a.retry_cooldown),
               "--blocked-pause", str(blocked_pause)]
        if acct:
            cmd += ["--account", acct]
        if a.headful:
            cmd += ["--headful"]
        workers.append(Worker(wid, acct, cmd, logs / f"{wid}.log"))
    for i, w in enumerate(workers):
        if i:
            time.sleep(a.stagger)
        w.start()
        print(f"started {w.wid} (pid {w.proc.pid}) -> {paths.rel(w.log_path)}")

    # --- supervise ---
    t0 = time.time()
    last = None
    try:
        while True:
            time.sleep(20)
            requeued, failed = q.sweep_stuck(con, a.stuck_after, a.stuck_cap)
            if requeued or failed:
                print(f"sweep: {requeued} stuck task(s) requeued, {failed} failed after {a.stuck_cap} stalls")
            for w in workers:
                if w.stopped or w.proc.poll() is None:
                    continue
                code = w.proc.returncode
                w.kill_tree()                    # clean up any Chrome left behind
                released = q.release_worker(con, w.wid)
                if code == 0:
                    w.stopped = True
                    print(f"{w.wid} finished")
                elif code == 3:
                    w.stopped = True
                    print(f"{w.wid} stopped: login for '{w.account}' needs a person "
                          f"(python -m scraper.{a.model}_scraper --login --profile {w.account})")
                elif w.restarts >= a.max_restarts:
                    w.stopped = True
                    print(f"{w.wid} exited with {code}; restart limit reached, giving up on it")
                else:
                    w.restarts += 1
                    print(f"{w.wid} exited with {code}; released {released} task(s); restart {w.restarts}")
                    w.start()
            c = q.counts(con)
            if c != last:
                print(f"{time.strftime('%H:%M:%S')} {c} | {time.time() - t0:.0f}s")
                last = c
            if q.open_work(con) == 0:
                break
            if all(w.stopped for w in workers):
                print("All workers stopped with work left; resume later with the same command.")
                break
    except KeyboardInterrupt:
        print("\nInterrupted; stopping workers. Re-run the same command to resume.")
    finally:
        for w in workers:
            w.kill_tree()
            q.release_worker(con, w.wid)

    raw_path, clean_path = q.export(con, a.model, a.dates)
    c = q.counts(con)
    n_att = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    print(f"\nDone in {time.time() - t0:.0f}s | {c} | attempts={n_att}")
    print(f"raw:   {paths.rel(raw_path)}\nclean: {paths.rel(clean_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
