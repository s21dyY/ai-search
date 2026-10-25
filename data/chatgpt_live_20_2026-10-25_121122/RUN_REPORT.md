# ChatGPT guest scraper — 20-article live verification

Date: 2026-10-25. Final run passed all 20 rows. The runner closed the guest browser in its finally block.

## Production integration

- Registered a response observer before navigation using Page.addScriptToEvaluateOnNewDocument.
- Read a clone of the normal guest conversation NDJSON response; the original response remains available to ChatGPT.
- Captured status.reasoning.items/activeItem searchSources groups as they arrive, before activity is hidden.
- Mapped URL/title/optional snippet to the existing source schema and deduplicated URLs per row.
- response_search_results now uses the exposed guest search-activity results when the old More heading is absent. The original return None line remains commented.
- Citation extraction now prefers the current Cite component snapshot from the same stream. The previous DOM/popover extraction remains below it as fallback, and the older panel parser is retained.
- Preserved existing source-error messages, match flags, CLI arguments and other-provider behavior. Updated README documentation.

## Live test scope

The actual RunChatGPTScraper entrypoint processed 20 distinct article IDs selected from dataset.csv: the original three test articles plus 17 evenly spaced across the remaining eligible unique IDs. The selected sample spans entertainment, news, sports and money. Source CSV records, IDs and headlines are recorded in selection.json. Nested pageURL and section fields were normalized to the format expected by the existing Gannett API reader.

All 20 prompts were generated through fresh Gemini API calls with the existing configured gemini-3.5-flash-lite model. The temporary test harness disabled prompt fallback to avoid hiding API failures. No answers, citations or search results were mocked. All 20 queries used the same fresh unsigned-in browser profile, with the existing delays intact. There was no account login, quota rejection or access gate during the final run.

The temporary harness added checkpoints, exact submitted-query checks and failure diagnostics; it did not replace production query, response or source logic. The script was removed after validation.

## Verification

| Check | Result |
|---|---:|
| Distinct articles processed | 20/20 |
| Fresh Gemini prompts | 20/20 |
| Exact submitted-question matches | 20/20 |
| Answers collected | 20/20 |
| Valid citation JSON lists | 20/20 |
| Valid search-result JSON lists | 20/20 |
| Rows with result URLs outside their citation list | 20/20 |
| Source-column errors | 0 |
| Citation entries across rows | 119 |
| Search-result entries across rows | 249 |
| Normal source-match screenshots verified | 9 |

Each list was checked for nonempty URLs and headlines, valid JSON, and duplicate URL removal. Match flags were verified as numeric 0/1. The final CSV was read back and compared with the prompt records, submitted questions, per-row checks and selected IDs. The scraper SHA-256 matches the file tested for the entire final run. Python syntax, JavaScript syntax and git diff whitespace checks passed. A replay against the previously captured normal response recovered the expected 16 search results and 9 final citations while leaving the original response body unchanged.

## Per-article results

| # | Headline | Answer words | Citations | Search results | Result URLs outside citation list |
|---:|---|---:|---:|---:|---:|
| 1 | Why widow of Michael Crichton chose James Patterson to finish his 'Eruption' book | 430 | 6 | 17 | 11 |
| 2 | Huge Roxbury warehouse proposal in jeopardy as planning board pushes back. What happened | 509 | 11 | 15 | 6 |
| 3 | Delbarton alum Jack Alexy of Mendham qualifies for U.S. swim team at Paris Olympics | 421 | 6 | 10 | 4 |
| 4 | Omarosa slams Donald Trump's 'Black jobs' debate comments, compares remarks to 'slavery' | 588 | 5 | 12 | 8 |
| 5 | Four Tops singer sues hospital for discrimination, claims staff ordered psych eval | 488 | 5 | 9 | 4 |
| 6 | Justin Timberlake arrested on DWI charges in the Hamptons, reports say | 686 | 9 | 14 | 8 |
| 7 | This summer's most anticipated movie releases \| The Excerpt | 1313 | 8 | 10 | 3 |
| 8 | Taylor Swift breaks attendance record for female artist in Lyon, France | 105 | 6 | 9 | 3 |
| 9 | Oprah says book club pick 'Familiaris' by David Wroblewski 'brilliantly' explores life's purpose | 1094 | 9 | 16 | 8 |
| 10 | Naomi Watts and Billy Crudup get married – again! See the gorgeous ceremony | 419 | 7 | 13 | 6 |
| 11 | 'Rust' armorer Hannah Gutierrez-Reed denied immunity to testify at Alec Baldwin's trial | 366 | 3 | 16 | 13 |
| 12 | Kevin Costner's new 'Horizon' movie: Why he needs 'Yellowstone' fans and John Dutton | 664 | 5 | 8 | 3 |
| 13 | Dover will open new Morris Canal trail on Saturday. Take a hike into history | 309 | 7 | 12 | 8 |
| 14 | These are the fireworks shows in your North Jersey towns for July 4th. See when and where | 544 | 3 | 9 | 6 |
| 15 | Who says you can't go 'Home'? Revival on Broadway packed with melody, rhythm | 616 | 8 | 7 | 2 |
| 16 | Ramapo, Indian Hills enrollment disparity study completed. Here's what was found | 210 | 3 | 10 | 7 |
| 17 | Montclair University sergeant charged in PBA card fraud enrolls in PTI, loses job | 293 | 4 | 14 | 10 |
| 18 | Softball: Morris Knolls holds off rival Morris Hills to claim second straight sectional title | 127 | 2 | 17 | 15 |
| 19 | Think building on empty land will solve your homebuying woes? Consider these factors first | 2170 | 4 | 12 | 8 |
| 20 | This skyscraper expert says high-rises are the future. Why we might see more in NJ | 507 | 8 | 19 | 12 |

## Preliminary run

The preliminary run in ../chatgpt_live_20_2026-10-25_120638 was intentionally paused after three completed rows and a fourth prompt call. Search-result capture succeeded on all three completed rows, but the warehouse citation popover timed out. Reading Cite records from the same response stream addressed that independent failure; the final 20-row test above used that version throughout. The preliminary run is not included in the 20 successful rows. There were four fresh prompt calls in that preliminary attempt and 20 in the final run.

## Data interpretation

response_search_results contains the guest search-activity list and can overlap with citations. It is not assumed to include every URL in the citation list, nor every page considered internally by the model. URL-set differences count different URL strings; variants may identify the same underlying article. Match flags and screenshots retain the existing candidate-detection semantics, not proof of copying. This verification covers execution and data capture.

## Artifacts

- gannett_gpt_2026-10-25.csv — full final results.
- article_summary.csv — compact per-article counts and outcomes.
- verification.json — final checks and aggregate counts.
- selection.json and data/gannett_API_data_2026-10-25.csv — selected input/provenance.
- prompt_provenance.json and submitted_queries.json — fresh prompts and exact UI question comparisons.
- live_checkpoint.csv and run.log — checkpoints/progress.
- screenshots_gpt_2026-10-25/ — normal source-match screenshots.
