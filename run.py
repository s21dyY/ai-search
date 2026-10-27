"""
run.py
------
One command for the whole pipeline:

    python run.py

It asks a few questions (press Enter to accept the default in [brackets]) and then:
  1. gets the input: an existing file, the Gannett API (for a date), or a test sample
  2. checks every account is logged in on each site, logging in again if needed
  3. runs ChatGPT and Perplexity at the same time, one worker per account
  4. prints a summary and, if you want, runs analysis/Analysis_Metrics.py

Everything can also be given as options, for example:

    python run.py --name 2026-10-20 --sites chatgpt,perplexity --limit 50 --yes
    python run.py --name mytest --test-articles 6 --yes

Run it from anywhere; it switches to the project's venv by itself.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / "venv" / "bin" / "python"

# Re-run inside the project's venv if started with another Python.
if VENV_PY.exists() and Path(sys.prefix).resolve() != (ROOT / "venv").resolve() and not os.environ.get("RUN_PY_NO_VENV"):
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from scraper import paths                      # noqa: E402
from scraper.accounts import load_accounts     # noqa: E402

SITES = ["chatgpt", "perplexity"]
PROGRESS_EVERY = 60                              # seconds between progress lines
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(_\d{2})?$")
YES = False                                    # set by --yes


# -- small helpers ---------------------------------------------------------------

def say(msg=""):
    print(msg, flush=True)


def ask(question: str, default: str = "") -> str:
    if YES:
        say(f"{question} [{default}]: {default}")
        return default
    try:
        ans = input(f"{question} [{default}]: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def ask_yes(question: str, default: bool = True) -> bool:
    ans = ask(question + (" (Y/n)" if default else " (y/N)"), "y" if default else "n").lower()
    return ans.startswith("y")


def py(*args, **kw):
    return subprocess.run([sys.executable, *args], cwd=ROOT, **kw)


# -- steps -----------------------------------------------------------------------

def default_date() -> str:
    """Yesterday: the most recent day whose articles are all published."""
    import datetime as dt
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def resolve_name(name: str) -> str:
    import datetime as dt
    shortcuts = {"yesterday": default_date(), "today": dt.date.today().isoformat()}
    return shortcuts.get(name.lower(), name)


def unfinished(run: str) -> str:
    """'chatgpt: 3 pending, 1 failed' for runs with work left, else ''."""
    import sqlite3
    parts = []
    for site in SITES:
        db = paths.queue_db(run, site)
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            c = dict(con.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
            con.close()
        except Exception:
            continue
        left = {k: c.get(k, 0) for k in ("pending", "running", "failed") if c.get(k)}
        if left:
            parts.append(f"{site}: " + ", ".join(f"{v} {k}" for k, v in left.items()))
    return "; ".join(parts)


def choose_name(arg: str | None) -> str:
    if arg:
        return resolve_name(arg)
    runs = [p.name for p in sorted((p for p in paths.DATA.iterdir() if p.is_dir() and p.name != "page-samples"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)] if paths.DATA.exists() else []
    dated = [r for r in runs if DATE_RE.match(r)]
    if dated:
        say("Recent dated runs: " + ", ".join(dated[:6]))
    left = [(r, unfinished(r)) for r in runs[:10]]
    for r, info in left:
        if info:
            say(f"Unfinished: {r} ({info}). Enter its name to resume.")
    say("Enter a date (YYYY-MM-DD, YYYY-MM-DD_DD for a range, 'today' or 'yesterday') for real data,")
    say("or any other name for a test run on sample articles.")
    while True:
        name = resolve_name(ask("Run name", default_date()))
        if re.match(r"^[A-Za-z0-9_.-]+$", name):
            return name
        say("Use letters, digits, '-', '_' or '.' only.")


def ensure_input(name: str, test_articles: int | None) -> bool:
    inp = paths.input_csv(name)
    if inp.exists():
        import pandas as pd
        n = len(pd.read_csv(inp, usecols=[0]))
        say(f"Input: {paths.rel(inp)} ({n} articles)")
        return True

    if DATE_RE.match(name) and test_articles is None:
        # Real date: only real articles. Never put sample articles under a date name.
        if not os.environ.get("GANNETT_API_KEY"):
            say(f"No input for {name}, and GANNETT_API_KEY is not set, so its articles cannot be fetched.")
            say("Set it with:  export GANNETT_API_KEY=...   then run again.")
            say("To try the pipeline without a key, use a test name instead, e.g.  python run.py --name mytest")
            return False
        say(f"Fetching articles for {name} from the Gannett API...")
        r = py("-m", "ingest.Gannett_API", name)
        if r.returncode == 0 and paths.input_csv(name).exists():
            return ensure_input(name, None)
        say("The API fetch failed; see the message above.")
        return False

    n = test_articles
    if n is None:
        if not ask_yes(f"'{name}' is a test name. Create a test input from the sample dataset?"):
            return False
        n = int(ask("How many articles", "6"))
    r = py("tools/make_test_input.py", "--name", name, "--n", str(n), capture_output=True, text=True)
    if r.returncode != 0:
        say(r.stdout + r.stderr)
        return False
    return ensure_input(name, None)


def choose_sites(arg: str | None) -> list[str]:
    raw = arg or ask("Sites to run (chatgpt, perplexity, or both)", "both")
    raw = raw.replace(" ", "").lower()
    sites = SITES if raw in ("both", "all", "") else [s for s in raw.split(",") if s in SITES]
    if not sites:
        say("No valid site given; running both.")
        sites = SITES
    return sites


def check_accounts(sites: list[str], guest: bool) -> dict:
    """Returns {site: [account names]}; sites with no account are dropped (or run as guest)."""
    plan = {}
    if not Path("accounts.toml").exists():
        say("No accounts.toml. Copy accounts.example.toml to accounts.toml and add your accounts.")
    for site in sites:
        names = [a.name for a in load_accounts(service=site)]
        if names:
            plan[site] = names
            say(f"{site}: {len(names)} account(s): {', '.join(names)}")
        elif site == "chatgpt" and (guest or ask_yes("chatgpt: no account. Run one logged-out worker instead?", False)):
            plan[site] = []
            say("chatgpt: 1 logged-out worker")
        else:
            say(f"{site}: no account; skipping (Perplexity needs a logged-in account)")
    return plan


def check_logins(plan: dict) -> dict:
    """Open each account headless; log in automatically if the session expired.
    Falls back to a visible browser when Google needs a person. Drops accounts that fail."""
    from scraper.chatgpt_scraper import ChatGPTScraper
    from scraper.perplexity_scraper import PerplexityScraper
    from scraper.scraper_base import LoginChallenge, ScraperError, login_session
    classes = {"chatgpt": ChatGPTScraper, "perplexity": PerplexityScraper}
    ok_plan = {}
    for site, names in plan.items():
        ok_plan[site] = []
        for name in names:
            s, status = None, ""
            t0 = time.time()
            try:
                s = classes[site](headless=True, profile=name)
                s.open_new_chat()                      # logs in automatically if needed
                status = "ok"
            except LoginChallenge:
                status = "needs you"
            except ScraperError as e:
                status = f"error: {str(e)[:80]}"
            except Exception as e:
                status = f"error: {type(e).__name__}"
            finally:
                if s is not None:
                    s.close()
            if status == "needs you":
                say(f"  {site}/{name}: Google needs a manual step; opening a browser")
                login_session(classes[site], name)
                status = "ok (after manual step)"
            say(f"  {site}/{name}: {status} ({time.time() - t0:.0f}s)")
            if status.startswith("ok"):
                ok_plan[site].append(name)
        if names and not ok_plan[site]:
            say(f"  {site}: no account is logged in; skipping this site")
            del ok_plan[site]
    return ok_plan


def run_sites(name: str, plan: dict, limit: int | None, headful: bool, retry_failed: bool) -> dict:
    """Runs every site at once. Returns {site: exit code}; 0 means every article is done."""
    procs = []
    for i, (site, names) in enumerate(plan.items()):
        cmd = [sys.executable, "-m", "scraper.run_queue", "--model", site, "--dates", name, "--quiet"]
        cmd += ["--accounts", ",".join(names)] if names else ["--guest-workers", "1"]
        if limit:
            cmd += ["--limit", str(limit)]
        if headful:
            cmd += ["--headful"]
        if retry_failed:
            cmd += ["--retry-failed"]
        if i:
            time.sleep(3)
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        procs.append((site, p))

    def pump(site, p):
        for line in p.stdout:
            say(f"[{site:10}] {line.rstrip()}")

    finished = threading.Event()

    def progress():                          # one line for all sites together, every minute
        from scraper import queue_db as q
        t0 = time.time()
        while not finished.wait(PROGRESS_EVERY):
            total = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for site in plan:
                db = q.db_path(site, name)
                if db.exists():
                    con = q.connect(db)
                    for k, v in q.counts(con).items():
                        total[k] += v
                    con.close()
            n = sum(total.values())
            if n:
                say(f"{time.strftime('%H:%M')} | {total['done']} of {n} done, {total['failed']} failed, "
                    f"{total['running']} running, {total['pending']} waiting | {(time.time() - t0) / 60:.0f} min")

    threads = [threading.Thread(target=pump, args=(s, p), daemon=True) for s, p in procs]
    threads.append(threading.Thread(target=progress, daemon=True))
    for t in threads:
        t.start()
    try:
        for _, p in procs:
            p.wait()
    except KeyboardInterrupt:
        # Ctrl+C reaches the runners too; they stop their workers and save progress.
        say("\nStopping... (run the same command again to resume)")
        for _, p in procs:
            p.wait()
    finished.set()
    for t in threads:
        t.join(timeout=5)
    return {site: p.returncode for site, p in procs}


def summarize(name: str, sites: list[str]) -> list[Path]:
    import pandas as pd
    say("\n=== Summary ===")
    files = []
    for site in sites:
        f = paths.results_csv(name, site)
        if not f.exists():
            say(f"{site}: no results file")
            continue
        files.append(f)
        d = pd.read_csv(f)
        status = d["status"].value_counts().to_dict() if "status" in d else {}
        done = d[d.get("status", "") == "done"] if "status" in d else d
        orig_col = "original_in_sources" if site == "perplexity" else "original_in_citations"
        orig = int(done[orig_col].fillna(0).astype(int).sum()) if orig_col in done else 0
        say(f"{site:10} {len(d)} articles | {status} | original cited in {orig}/{len(done)} | {paths.rel(f)}")
    return files


def run_analysis(files: list[Path]) -> None:
    for f in files:
        say(f"\nAnalysis of {paths.rel(f)}:")
        r = subprocess.run([sys.executable, str(ROOT / "analysis" / "Analysis_Metrics.py"), str(f)],
                           cwd=f.parent, capture_output=True, text=True)
        out = sorted(f.parent.glob("analysis_summary_*.csv"))
        if r.returncode == 0 and out:
            say(f"  saved {paths.rel(out[-1])}")
        else:
            say("  failed: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])


# -- main --------------------------------------------------------------------------

def main():
    global YES
    p = argparse.ArgumentParser(description="Run the whole pipeline. With no options it asks what to do.")
    p.add_argument("--name", help="a date (YYYY-MM-DD, YYYY-MM-DD_DD, today, yesterday) or a test name; default: yesterday")
    p.add_argument("--sites", help="chatgpt, perplexity, or both (comma-separated)")
    p.add_argument("--limit", type=int, help="only the first N articles")
    p.add_argument("--test-articles", type=int, help="create a test input with N sample articles if none exists")
    p.add_argument("--guest", action="store_true", help="if accounts.toml has no ChatGPT account, run one logged-out ChatGPT worker without asking; "
                        "ChatGPT accounts, when present, are always used")
    p.add_argument("--skip-login-check", action="store_true")
    p.add_argument("--retry-failed", action="store_true", help="re-run articles that failed last time")
    p.add_argument("--headful", action="store_true", help="show the browser windows")
    p.add_argument("--no-analysis", action="store_true")
    p.add_argument("--yes", action="store_true", help="accept every default; no questions")
    a = p.parse_args()
    YES = a.yes

    say("=== LLM evidence gathering ===\n")
    name = choose_name(a.name)
    if not ensure_input(name, a.test_articles):
        say("No input; stopping.")
        return 1

    sites = choose_sites(a.sites)
    limit = a.limit
    if limit is None and not YES:
        lim = ask("Only the first N articles? (Enter for all)", "all")
        limit = int(lim) if lim.isdigit() else None

    if not os.environ.get("OPENAI_API_KEY"):
        say("Note: OPENAI_API_KEY is not set; prompts use the fallback 'What can you tell me about: <headline>'.")

    plan = check_accounts(sites, a.guest)
    if not plan:
        say("Nothing to run.")
        return 1
    if not a.skip_login_check:
        say("\nChecking logins...")
        plan = check_logins(plan)
        if not plan:
            say("No site has a working login; stopping.")
            return 1

    say(f"\nRunning {', '.join(plan)} for '{name}'" + (f", first {limit} articles" if limit else "") + ".")
    say("Progress prints every minute. Ctrl+C stops; running the same command again resumes.\n")
    codes = run_sites(name, plan, limit, a.headful, a.retry_failed)

    files = summarize(name, list(plan))
    unfinished = [site for site, code in codes.items() if code != 0]
    if unfinished:
        say(f"\nWARNING: not every article finished on {', '.join(unfinished)}; those are empty rows in the results.\n"
            f"Try them again with: python run.py --name {name} --retry-failed")
    if files and not a.no_analysis and ask_yes("\nRun analysis/Analysis_Metrics.py on the results?",
                                               default=not unfinished):
        run_analysis(files)
    say(f"\nAll files for this run: {paths.rel(paths.run_dir(name))}/")
    return 1 if unfinished else 0


if __name__ == "__main__":
    sys.exit(main())
