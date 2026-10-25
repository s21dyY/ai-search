"""Run the local Gemini CSV test from the repository root.

This is a live integration test that makes Gemini API requests.
"""

import csv
from datetime import datetime, timezone
import time

from Prompt_Generator import PromptGenerator


INPUT_CSV = "data/prompt_generator_test.csv"
OUTPUT_CSV = "data/prompt_generator_test_results.csv"
REQUEST_INTERVAL_SECONDS = 20


def main():
    with open(INPUT_CSV, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames + ["model", "generated_prompt", "word_count", "tested_at_utc"]
        rows = list(reader)

    generator = PromptGenerator()
    print(f"Testing {len(rows)} articles with {generator.model}; {REQUEST_INTERVAL_SECONDS}s between requests.")
    print(f"Results will be written to {OUTPUT_CSV} (replaced on each run).")
    with generator.client, open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(rows):
            if index:
                time.sleep(REQUEST_INTERVAL_SECONDS)
            prompt = generator.generate(row["headline"], row.get("keywords", ""), fallback=False)
            writer.writerow({
                **row,
                "model": generator.model,
                "generated_prompt": prompt,
                "word_count": len(prompt.split()),
                "tested_at_utc": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[{index + 1}/{len(rows)}] {prompt}")


if __name__ == "__main__":
    main()
