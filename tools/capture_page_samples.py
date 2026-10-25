"""
Capture DOM snapshots of ChatGPT / Perplexity in guest mode at the moments the
queue worker needs to recognise, by driving the real scraper classes. So this
also smoke-tests chatgpt_scraper.py / perplexity_scraper.py.

Run from the repo root with the project venv:

    python tools/capture_page_samples.py chatgpt
    python tools/capture_page_samples.py perplexity

The browser opens visibly so you can pass a Cloudflare check or close a modal
by hand. The script pauses for Enter at a few points.

Output: data/page-samples/<target>/NN_<moment>.html and .png (gitignored)
"""

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chatgpt_scraper import ChatGPTScraper        # noqa: E402
from perplexity_scraper import PerplexityScraper  # noqa: E402

TARGETS = {"chatgpt": ChatGPTScraper, "perplexity": PerplexityScraper}

# A question that should trigger a web search and a reasonably long answer.
PROMPT = "What happened in the news today in the United States? Give me five stories with sources."


def snap(scraper, out_dir: Path, name: str):
    scraper.save_html(out_dir / f"{name}.html")
    scraper.screenshot(out_dir / f"{name}.png")
    print(f"  saved {name}.html/.png")


def main():
    args = sys.argv[1:]
    profile = None
    if "--profile" in args:
        i = args.index("--profile")
        profile = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or args[0] not in TARGETS:
        print("usage: python tools/capture_page_samples.py chatgpt|perplexity [--profile NAME]")
        sys.exit(1)
    target = args[0]
    out_dir = ROOT / "data" / "page-samples" / (f"{target}-{profile}" if profile else target)
    out_dir.mkdir(parents=True, exist_ok=True)

    scraper = TARGETS[target](headless=False, profile=profile)
    print(f"mode: {'account ' + profile if profile else 'guest'} | output: {out_dir}")
    try:
        print("[1] open landing page (ChatGPT: also turns on Web search)")
        try:
            scraper.open_new_chat()
        finally:
            snap(scraper, out_dir, "01_landing")

        input("\nIf a login modal or Cloudflare check is showing, deal with it in the browser.\n"
              "Then press Enter here to send the prompt... ")
        snap(scraper, out_dir, "01b_landing_ready")

        print("[2] ask")
        scraper.ask(PROMPT)
        for i, delay in enumerate((0.5, 2, 5), start=1):
            time.sleep(delay)
            print(f"  is_generating={scraper.is_generating()} answer_len={len(scraper.answer_text())}")
            snap(scraper, out_dir, f"02_generating_{i}")

        print("[3] wait_for_answer")
        try:
            scraper.wait_for_answer()
        finally:
            snap(scraper, out_dir, "03_done")
        print(f"  has_sources={scraper.has_sources()} answer_len={len(scraper.answer_text())}")

        print("[4] extract_sources (automatic attempt)")
        try:
            cites, more = scraper.extract_sources()
            print(f"  citations={len(cites)} search_results={len(more)}")
            for c in cites[:5]:
                print("   ", c["url"], "|", c["headline"][:60])
        except Exception:
            traceback.print_exc()
        snap(scraper, out_dir, "04_sources_auto")

        input("\nIf the sources panel is NOT open, click the sources control in the browser now.\n"
              "Then press Enter here... ")
        snap(scraper, out_dir, "04b_sources_open")

        input("\nOptional: trigger a guest limit or login wall (send more prompts by hand),\n"
              "then press Enter. Otherwise just press Enter... ")
        snap(scraper, out_dir, "05_extra")

    except Exception:
        traceback.print_exc()
        snap(scraper, out_dir, "99_error")
    finally:
        scraper.close()
        print(f"\nDone. Files are in {out_dir}")


if __name__ == "__main__":
    main()
