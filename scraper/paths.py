"""
paths.py
--------
Where a run's files live. One folder per run (named by the --dates label), one
subfolder per site:

    data/<dates>/
        gannett_API_data_<dates>.csv        input (ingest/Gannett_API.py or tools/make_test_input.py)
        chatgpt/
            gannett_chatgpt_<dates>.csv     per-article results, read by analysis/Analysis_Metrics.py
            gannett_chatgpt_<dates>_raw.csv one row per attempt
            queue.db                        task queue; needed to resume, retry or re-export
            logs/                           one log per worker
            screenshots/                    matches found, and errors/
        perplexity/
            ...

The result file names keep the old pattern because Analysis_Metrics.py reads the
site and date from the file name.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def run_dir(dates: str) -> Path:
    return DATA / dates


def site_dir(dates: str, model: str) -> Path:
    return DATA / dates / model


def input_csv(dates: str) -> Path:
    """data/<dates>/gannett_API_data_<dates>.csv; falls back to the old flat location."""
    new = run_dir(dates) / f"gannett_API_data_{dates}.csv"
    old = DATA / f"gannett_API_data_{dates}.csv"
    return old if (old.exists() and not new.exists()) else new


def results_csv(dates: str, model: str) -> Path:
    return site_dir(dates, model) / f"gannett_{model}_{dates}.csv"


def raw_csv(dates: str, model: str) -> Path:
    return site_dir(dates, model) / f"gannett_{model}_{dates}_raw.csv"


def queue_db(dates: str, model: str) -> Path:
    return site_dir(dates, model) / "queue.db"


def logs_dir(dates: str, model: str) -> Path:
    return site_dir(dates, model) / "logs"


def screenshots_dir(dates: str, model: str) -> Path:
    return site_dir(dates, model) / "screenshots"


def rel(path: str | Path) -> str:
    """Path relative to the repo root, for messages and for paths stored in CSVs."""
    try:
        return os.path.relpath(Path(path).resolve(), ROOT)
    except ValueError:
        return str(path)
