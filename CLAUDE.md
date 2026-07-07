# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python CLI tool that reads a text file of words (one per line), looks up kid-friendly definitions and synonyms via the Merriam-Webster Elementary Dictionary and Intermediate Thesaurus APIs (falling back to NLTK WordNet when no API key is configured or a word isn't found), and generates a styled, colorful PDF dictionary alongside a matching-test PDF and matching answer-key PDF for the same word list.

## Commands

```bash
# One-time setup: create the virtual environment and install dependencies
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Activate the venv so `python` below resolves to it (PowerShell)
.venv\Scripts\Activate.ps1

# Run with default output (dictionary.pdf + test.pdf)
python dictionary_app.py words.txt

# Run with custom output filenames
python dictionary_app.py words.txt -o custom_name.pdf -t custom_test.pdf -a custom_answers.pdf

# Bypass the cache entirely (always look up fresh, don't store results)
python dictionary_app.py words.txt --no-cache

# Ignore cached entries and re-fetch, overwriting the cache
python dictionary_app.py words.txt --refresh-cache
```

Without activating, prefix any command with `.venv\Scripts\python.exe` instead of `python`.

## Setup: Merriam-Webster API keys

Register for free keys at https://www.dictionaryapi.com/register/index — sign up for the **Elementary Dictionary** and **Intermediate Thesaurus** APIs separately, then paste both keys into `config.ini`:

```ini
[merriam_webster]
dictionary_key = YOUR_DICTIONARY_KEY_HERE
thesaurus_key = YOUR_THESAURUS_KEY_HERE
```

`config.ini` is read from the same directory as `dictionary_app.py`. If keys are missing or left as placeholders, the app prints a warning and falls back to WordNet for both definitions and synonyms — it still runs, just with less kid-tailored wording.

## Architecture

Single-file app (`dictionary_app.py`) with seven layers:

1. **Word reader** (`read_words`) — reads input file, strips blanks, deduplicates, sorts alphabetically
2. **Config loader** (`load_config`) — reads `config.ini` for the two Merriam-Webster API keys
3. **Local cache** (`init_cache_db`, `cache_get`, `cache_put`, `lookup_word_cached`) — SQLite database (default `dictionary_cache.db`, next to the script) that stores looked-up entries so repeat runs over the same word lists skip network/WordNet calls entirely. Normalized schema: `entries` (word + source, `UNIQUE(word, source)` so the same word can have separate cached rows per source, e.g. one `MW` row and one `WN` row), `meanings` (part of speech, FK to entry), `definitions` (definition text + example, FK to meaning), `synonyms` (FK to entry) — `meanings`/`definitions`/`synonyms` all have a `position` column to preserve original ordering and cascade-delete when their parent entry/meaning is deleted. `cache_get(conn, word, source=None)` returns the `MW` row if present, else `WN` (see `SOURCE_PRIORITY`), or a specific source if requested. `cache_put` deletes and reinserts the `(word, source)` row so updates never duplicate. `--no-cache` disables reading/writing it; `--refresh-cache` re-fetches and overwrites cached rows; `--cache-db PATH` points at a different database file.
4. **Lookup** (`lookup_word`) — tries `lookup_word_mw_dictionary` (Elementary Dictionary `sd2` reference) for definitions and `lookup_word_mw_synonyms` (Intermediate Thesaurus `ithesaurus` reference) for synonyms; falls back to `lookup_word_wordnet`/`wordnet_synonyms` (NLTK WordNet, offline) when a key is missing or the word isn't found. M-W response text contains run-in markup tokens (`{bc}`, `{sx|...}`, etc.) cleaned up by `_clean_mw_text`. Max 2 definitions per part of speech, max 8 synonyms. Each returned entry carries a `source` field (`"MW"` or `"WN"`) used both for the cache and the PDF's source tag.
5. **Dictionary PDF builder** (`build_pdf`) — uses reportlab's `SimpleDocTemplate`/`Platypus` to produce a Letter-size PDF; each word's full entry is wrapped in `KeepTogether` so it never splits across a page break
6. **Test PDF builder** (`build_test_pdf`) — produces a second Letter-size PDF: a question section listing every word (in the same alphabetical order as the dictionary) next to an empty answer box, followed by a page break and a "Definitions" section listing one definition per word (`_first_definition`, the first definition of the first meaning) in shuffled order and numbered 1..N. Students write the matching definition number in the box next to each word.
7. **Answer key PDF builder** (`build_answer_key_pdf`) — produces a third Letter-size PDF reusing the same word/answer-box table layout as the test paper, but with each box pre-filled with the correct definition number. `main()` calls `shuffle_definition_order(entries)` once to get the shuffled definition order, then passes that same `shuffled_indices` list to both `build_test_pdf` and `build_answer_key_pdf` so the two PDFs are guaranteed to agree; `_answer_numbers(shuffled_indices)` inverts the shuffle to get each word's correct 1-based definition number. The word/answer-box table itself is shared via `_build_word_answer_table(entries, answers=None)` — `answers=None` renders empty boxes (test paper), a list of ints renders bold centered numbers (answer key).

## PDF Layout

Dictionary (`build_pdf`):
- Word headings: 15pt bold dark blue (`#1a5276`)
- Parts of speech: 10pt italic gray
- Definitions: bulleted, 10pt black with optional italic example sentences (same size as definitions)
- Synonyms: 9pt green (`#27ae60`)
- Entries separated by light gray horizontal rules, kept together as a unit (never split across pages)
- 1-inch margins on all sides
- No title page — PDF starts directly with the first entry

Test paper (`build_test_pdf`):
- Title, Name/Date line, and instructions, then a three-column table (word, narrow gap, answer box) covering every word in order — the word cell is outlined in gray so the whitespace after short words stays visually grouped with that word, and a gap column keeps the outline from touching the black answer box, making it easier to find the right box when not working through words in order
- Page break, then a numbered, shuffled list of definitions (one per word, via `random.shuffle`)
- Same 1-inch margins and Letter page size as the dictionary

Answer key (`build_answer_key_pdf`):
- Same title/table styling as the test paper, minus the Name/Date line and Definitions page — just the word list with each answer box filled in with the correct definition number (bold, centered)
- Shares the exact word order and definition shuffle with `build_test_pdf` (both are built from the same `shuffled_indices` in `main()`) so the numbers always line up with the corresponding test paper

## Key Dependencies

- `requests` — HTTP calls to the Merriam-Webster APIs
- `reportlab` — PDF generation (Platypus flowables)
- `nltk` (WordNet corpus) — offline fallback dictionary/thesaurus when no API key is set or a word isn't found

## Error Handling

Words not found by either source, or network failures, print a warning and skip the word without crashing. An empty input file exits with an error message. A 0.5s delay is inserted between word lookups to avoid hitting rate limits.
