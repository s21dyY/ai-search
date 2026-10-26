"""
Build a small test input from the sample dataset, so the pipeline can be tested
without a Gannett API key.

    python tools/make_test_input.py --name partest --n 6

writes data/partest/gannett_API_data_partest.csv with 6 random recent articles from
ingest/dataset.csv. Then run, for example:

    python -m scraper.run_queue --model chatgpt --dates partest
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scraper.scraper_base import article_url_of  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="partest", help="label used as --dates in run_queue")
    p.add_argument("--n", type=int, default=6, help="number of articles")
    p.add_argument("--seed", type=int, default=0, help="change to get different articles")
    a = p.parse_args()

    src = ROOT / "ingest" / "dataset.csv"
    df = pd.read_csv(src, usecols=["headline", "keywords", "pageURL", "publishDate", "fullText",
                                   "type", "classificationV2"], low_memory=False)
    df = df.dropna(subset=["headline", "pageURL"]).sort_values("publishDate", ascending=False)

    # Same columns as ingest/Gannett_API.py produces: plain pageURL, section, subsection.
    def classification(v, key):
        try:
            return json.loads(v)["classificationV2"].get(key, "")
        except Exception:
            return ""
    df["section"] = df["classificationV2"].map(lambda v: classification(v, "section"))
    df["subsection"] = df["classificationV2"].map(lambda v: classification(v, "subsection"))
    df["pageURL"] = df["pageURL"].map(article_url_of)
    df = df[["headline", "fullText", "type", "publishDate", "pageURL", "section", "subsection", "keywords"]]
    pool = df.head(max(200, a.n))
    out = ROOT / "data" / a.name / f"gannett_API_data_{a.name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pool.sample(min(a.n, len(pool)), random_state=a.seed).to_csv(out, index=False)
    print(f"wrote {out.relative_to(ROOT)} ({min(a.n, len(pool))} articles)")
    print(f"next: python -m scraper.run_queue --model chatgpt --dates {a.name}")


if __name__ == "__main__":
    main()
