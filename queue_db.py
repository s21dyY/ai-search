"""
queue_db.py
-----------
SQLite task queue shared by the orchestrator (run_queue.py) and the workers
(worker.py). One database per model and date: data/queue_{model}_{dates}.db.

Design: local-docs/prd-parallel-runs-and-retries.md sections 5 and 6.

tasks     one row per article; status pending -> running -> done | failed
attempts  one row per try, written before the task status changes
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY,
    article_url    TEXT NOT NULL UNIQUE,
    headline       TEXT,
    keywords       TEXT,
    publish_date   TEXT,
    section        TEXT,
    prompt         TEXT,
    prompt_source  TEXT,
    model          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    tries          INTEGER NOT NULL DEFAULT 0,
    stuck_count    INTEGER NOT NULL DEFAULT 0,
    next_run_at    REAL NOT NULL DEFAULT 0,
    worker_id      TEXT,
    started_at     REAL,
    heartbeat_at   REAL,
    finished_at    REAL,
    last_error     TEXT
);
CREATE INDEX IF NOT EXISTS tasks_claim ON tasks(status, next_run_at, tries, id);

CREATE TABLE IF NOT EXISTS attempts (
    id                              INTEGER PRIMARY KEY,
    task_id                         INTEGER NOT NULL REFERENCES tasks(id),
    attempt_no                      INTEGER NOT NULL,
    worker_id                       TEXT,
    account                         TEXT,
    outcome                         TEXT NOT NULL,
    error_class                     TEXT,
    error_message                   TEXT,
    started_at                      REAL,
    finished_at                     REAL,
    request_time                    TEXT,
    response_text                   TEXT,
    response_plain                  TEXT,
    searched                        INTEGER,
    response_citations              TEXT,
    response_search_results         TEXT,
    response_images                 TEXT,
    n_citations                     INTEGER,
    n_search_results                INTEGER,
    n_search_results_not_cited      INTEGER,
    search_results_status           TEXT,
    original_in_citations           INTEGER,
    original_in_search_results      INTEGER,
    republisher_in_citations        INTEGER,
    republisher_in_search_results   INTEGER,
    screenshot_path                 TEXT
);
CREATE INDEX IF NOT EXISTS attempts_task ON attempts(task_id);
"""

ATTEMPT_FIELDS = [
    "request_time", "response_text", "response_plain", "searched",
    "response_citations", "response_search_results", "response_images",
    "n_citations", "n_search_results", "n_search_results_not_cited", "search_results_status",
    "original_in_citations", "original_in_search_results",
    "republisher_in_citations", "republisher_in_search_results", "screenshot_path",
]


def db_path(model: str, dates: str) -> Path:
    return Path("data") / f"queue_{model}_{dates}.db"


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60, isolation_level=None)  # autocommit; explicit BEGIN
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


# -- orchestrator side ----------------------------------------------------------

def enqueue(con, model: str, articles: list[dict]) -> tuple[int, int]:
    """Insert one pending task per article not already in the queue. Returns (added, existing)."""
    added = existing = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for a in articles:
            cur = con.execute(
                "INSERT OR IGNORE INTO tasks(article_url, headline, keywords, publish_date, section,"
                " prompt, prompt_source, model) VALUES (?,?,?,?,?,?,?,?)",
                (a["article_url"], a.get("headline"), a.get("keywords"), a.get("publish_date"),
                 a.get("section"), a.get("prompt"), a.get("prompt_source"), model))
            if cur.rowcount:
                added += 1
            else:
                existing += 1
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return added, existing


def known_urls(con) -> set:
    return {r[0] for r in con.execute("SELECT article_url FROM tasks")}


def sweep_stuck(con, stuck_after: float, stuck_cap: int) -> tuple[int, int]:
    """Running tasks with no heartbeat for stuck_after seconds go back to pending
    (stuck_count + 1), or to failed once stuck_count reaches stuck_cap."""
    now = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        failed = con.execute(
            "UPDATE tasks SET status='failed', finished_at=?, worker_id=NULL, stuck_count=stuck_count+1,"
            " last_error='stuck: no heartbeat' WHERE status='running' AND heartbeat_at < ? AND stuck_count+1 >= ?",
            (now, now - stuck_after, stuck_cap)).rowcount
        requeued = con.execute(
            "UPDATE tasks SET status='pending', worker_id=NULL, stuck_count=stuck_count+1, next_run_at=?,"
            " last_error='stuck: no heartbeat' WHERE status='running' AND heartbeat_at < ?",
            (now, now - stuck_after)).rowcount
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return requeued, failed


def release_worker(con, worker_id: str) -> int:
    """A worker died: return its running task to pending at once (counts as stuck)."""
    return con.execute(
        "UPDATE tasks SET status='pending', worker_id=NULL, stuck_count=stuck_count+1, next_run_at=?,"
        " last_error='worker died' WHERE status='running' AND worker_id=?",
        (time.time(), worker_id)).rowcount


def counts(con) -> dict:
    out = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for r in con.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status"):
        out[r[0]] = r[1]
    return out


def open_work(con) -> int:
    return con.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('pending','running')").fetchone()[0]


# -- worker side ----------------------------------------------------------------

def claim(con, worker_id: str):
    """Atomically take the next claimable task, or None."""
    now = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute(
            "SELECT * FROM tasks WHERE status='pending' AND next_run_at <= ? ORDER BY tries, id LIMIT 1",
            (now,)).fetchone()
        if row is None:
            con.execute("COMMIT")
            return None
        con.execute(
            "UPDATE tasks SET status='running', worker_id=?, started_at=?, heartbeat_at=? WHERE id=?",
            (worker_id, now, now, row["id"]))
        con.execute("COMMIT")
        return dict(row)
    except Exception:
        con.execute("ROLLBACK")
        raise


def heartbeat(con, task_id: int, worker_id: str):
    con.execute("UPDATE tasks SET heartbeat_at=? WHERE id=? AND worker_id=?", (time.time(), task_id, worker_id))


def record_attempt(con, task: dict, worker_id: str, account: str | None, outcome: str,
                   started_at: float, row: dict | None = None, error_class: str = "",
                   error_message: str = "", screenshot_path: str = "") -> int:
    attempt_no = con.execute("SELECT COUNT(*) FROM attempts WHERE task_id=?", (task["id"],)).fetchone()[0] + 1
    vals = {k: (row or {}).get(k) for k in ATTEMPT_FIELDS}
    if screenshot_path and not vals.get("screenshot_path"):
        vals["screenshot_path"] = screenshot_path
    cols = ["task_id", "attempt_no", "worker_id", "account", "outcome", "error_class", "error_message",
            "started_at", "finished_at"] + ATTEMPT_FIELDS
    params = [task["id"], attempt_no, worker_id, account, outcome, error_class, error_message[:500],
              started_at, time.time()] + [vals[k] for k in ATTEMPT_FIELDS]
    con.execute(f"INSERT INTO attempts({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", params)
    return attempt_no


def finish(con, task_id: int, worker_id: str, status: str, error: str = ""):
    con.execute("UPDATE tasks SET status=?, finished_at=?, worker_id=NULL, last_error=? WHERE id=? AND worker_id=?",
                (status, time.time(), error[:500], task_id, worker_id))


def retry_later(con, task_id: int, worker_id: str, cooldown: float, max_tries: int, error: str) -> str:
    """Retryable failure: tries+1; pending after cooldown, or failed at max_tries. Returns new status."""
    tries = con.execute("SELECT tries FROM tasks WHERE id=?", (task_id,)).fetchone()[0] + 1
    status = "failed" if tries >= max_tries else "pending"
    con.execute("UPDATE tasks SET status=?, tries=?, next_run_at=?, worker_id=NULL, last_error=?,"
                " finished_at=CASE WHEN ?='failed' THEN ? ELSE finished_at END WHERE id=? AND worker_id=?",
                (status, tries, time.time() + cooldown, error[:500], status, time.time(), task_id, worker_id))
    return status


def give_back(con, task_id: int, worker_id: str, error: str):
    """Blocked: back to pending now, tries unchanged; another worker may take it."""
    con.execute("UPDATE tasks SET status='pending', next_run_at=?, worker_id=NULL, last_error=? WHERE id=? AND worker_id=?",
                (time.time(), error[:500], task_id, worker_id))


# -- export ---------------------------------------------------------------------

def export(con, model: str, dates: str, out_dir: str | Path = "data") -> tuple[Path, Path]:
    """raw: every attempt joined with its task. clean: one row per done task (last done attempt)."""
    out_dir = Path(out_dir)
    raw = pd.read_sql_query(
        "SELECT t.id AS task_id, t.article_url AS pageURL, t.headline, t.keywords, t.publish_date,"
        " t.section, t.prompt, t.prompt_source, t.status AS task_status, t.tries, t.stuck_count,"
        " a.* FROM attempts a JOIN tasks t ON t.id = a.task_id ORDER BY t.id, a.attempt_no", con)
    raw = raw.loc[:, ~raw.columns.duplicated()]
    for c in ("started_at", "finished_at"):
        if c in raw:
            raw[c] = pd.to_datetime(raw[c], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")
    raw_path = out_dir / f"gannett_{model}_{dates}_raw.csv"
    raw.to_csv(raw_path, index=False)
    done = raw[raw["outcome"] == "done"].sort_values(["task_id", "attempt_no"]).groupby("task_id").tail(1)
    clean_path = out_dir / f"gannett_{model}_{dates}.csv"
    done.to_csv(clean_path, index=False)
    return raw_path, clean_path


def load_articles(path: str | Path) -> list[dict]:
    """Input CSV from Gannett_API.py. pageURL may be a plain URL or the API's JSON blob."""
    df = pd.read_csv(path, low_memory=False)

    def url_of(v):
        s = str(v or "").strip()
        if s.startswith("{"):
            try:
                d = json.loads(s)
                d = d.get("pageURL", d)
                return d.get("long") or d.get("short") or ""
            except Exception:
                return ""
        return s

    out = []
    for _, r in df.iterrows():
        url = url_of(r.get("pageURL"))
        if not url:
            continue
        kw = r.get("keywords", "")
        out.append({
            "article_url": url,
            "headline": "" if pd.isna(r.get("headline")) else str(r.get("headline")),
            "keywords": "" if pd.isna(kw) else str(kw),
            "publish_date": "" if pd.isna(r.get("publishDate")) else str(r.get("publishDate")),
            "section": "" if pd.isna(r.get("section", "")) else str(r.get("section", "")),
        })
    return out
