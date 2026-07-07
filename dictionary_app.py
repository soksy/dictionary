import argparse
import configparser
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
import requests
from nltk.corpus import wordnet
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether,
    Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_LEFT


BLUE = HexColor("#1a5276")
GRAY = HexColor("#666666")
GREEN = HexColor("#27ae60")
LIGHT_GRAY = HexColor("#cccccc")
BLACK = HexColor("#000000")
SOURCE_COLOR = "#e67e22"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
CACHE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictionary_cache.db")
MW_DICT_URL = "https://www.dictionaryapi.com/api/v3/references/sd2/json/{word}?key={key}"
MW_THESAURUS_URL = "https://www.dictionaryapi.com/api/v3/references/ithesaurus/json/{word}?key={key}"
PLACEHOLDER_KEYS = {"", "YOUR_DICTIONARY_KEY_HERE", "YOUR_THESAURUS_KEY_HERE"}
SOURCE_PRIORITY = {"MW": 0, "WN": 1}


def load_config():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    dict_key = config.get("merriam_webster", "dictionary_key", fallback="").strip().strip('"\'')
    thes_key = config.get("merriam_webster", "thesaurus_key", fallback="").strip().strip('"\'')
    if dict_key in PLACEHOLDER_KEYS:
        print("Warning: no Merriam-Webster dictionary key in config.ini - using WordNet for all definitions.")
        dict_key = ""
    if thes_key in PLACEHOLDER_KEYS:
        thes_key = ""
    return dict_key, thes_key


def init_cache_db(path=CACHE_DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(word, source)
        );
        CREATE TABLE IF NOT EXISTS meanings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            part_of_speech TEXT NOT NULL,
            position INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meaning_id INTEGER NOT NULL REFERENCES meanings(id) ON DELETE CASCADE,
            definition TEXT NOT NULL,
            example TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS synonyms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            synonym TEXT NOT NULL,
            position INTEGER NOT NULL
        );
    """)
    conn.commit()
    return conn


def cache_get(conn, word, source=None):
    if source:
        row = conn.execute(
            "SELECT id, source FROM entries WHERE word = ? AND source = ?",
            (word, source),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, source FROM entries WHERE word = ?", (word,)
        ).fetchall()
        row = min(row, key=lambda r: SOURCE_PRIORITY.get(r[1], 99), default=None) if row else None
    if not row:
        return None

    entry_id, source = row
    meanings = []
    for meaning_id, pos in conn.execute(
        "SELECT id, part_of_speech FROM meanings WHERE entry_id = ? ORDER BY position",
        (entry_id,),
    ).fetchall():
        definitions = [
            {"definition": definition, "example": example}
            for definition, example in conn.execute(
                "SELECT definition, example FROM definitions WHERE meaning_id = ? ORDER BY position",
                (meaning_id,),
            ).fetchall()
        ]
        meanings.append({"partOfSpeech": pos, "definitions": definitions})

    synonyms = [
        row[0] for row in conn.execute(
            "SELECT synonym FROM synonyms WHERE entry_id = ? ORDER BY position",
            (entry_id,),
        ).fetchall()
    ]

    return {"word": word, "meanings": meanings, "synonyms": synonyms, "source": source}


def cache_put(conn, entry):
    word = entry["word"]
    source = entry.get("source", "unknown")
    fetched_at = datetime.now(timezone.utc).isoformat()

    cur = conn.cursor()
    cur.execute("DELETE FROM entries WHERE word = ? AND source = ?", (word, source))
    cur.execute(
        "INSERT INTO entries (word, source, fetched_at) VALUES (?, ?, ?)",
        (word, source, fetched_at),
    )
    entry_id = cur.lastrowid

    for m_pos, meaning in enumerate(entry["meanings"]):
        cur.execute(
            "INSERT INTO meanings (entry_id, part_of_speech, position) VALUES (?, ?, ?)",
            (entry_id, meaning["partOfSpeech"], m_pos),
        )
        meaning_id = cur.lastrowid
        for d_pos, defn in enumerate(meaning["definitions"]):
            cur.execute(
                "INSERT INTO definitions (meaning_id, definition, example, position) VALUES (?, ?, ?, ?)",
                (meaning_id, defn["definition"], defn.get("example", ""), d_pos),
            )

    for s_pos, synonym in enumerate(entry.get("synonyms", [])):
        cur.execute(
            "INSERT INTO synonyms (entry_id, synonym, position) VALUES (?, ?, ?)",
            (entry_id, synonym, s_pos),
        )

    conn.commit()


def lookup_word_cached(conn, word, dict_key, thes_key, refresh=False):
    if not refresh:
        cached = cache_get(conn, word)
        if cached:
            return cached, True

    result = lookup_word(word, dict_key, thes_key)
    if result:
        cache_put(conn, result)
    return result, False


def read_words(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        words = []
        seen = set()
        for line in f:
            word = line.strip().lower()
            if word and word not in seen:
                words.append(word)
                seen.add(word)
    if not words:
        print("Error: input file is empty or contains no valid words.")
        sys.exit(1)
    words.sort()
    return words


def _clean_mw_text(text):
    text = re.sub(r"\{bc\}", "", text)
    text = re.sub(r"\{sx\|([^|}]+)[^}]*\}", r"\1", text)
    text = re.sub(r"\{d_link\|([^|}]+)\|[^}]*\}", r"\1", text)
    text = re.sub(r"\{a_link\|([^}]+)\}", r"\1", text)
    text = re.sub(r"\{/?[a-z_]+\}", "", text)
    return text.strip()


def lookup_word_mw_dictionary(word, key):
    if not key:
        return None
    try:
        resp = requests.get(MW_DICT_URL.format(word=word, key=key), timeout=10)
    except requests.RequestException as e:
        print(f"network error ({e})", end=" ")
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None
    if not data or isinstance(data[0], str):
        return None

    meanings_by_pos = {}
    for sense in data:
        hw = sense.get("hwi", {}).get("hw", "").replace("*", "")
        if hw.lower() != word.lower():
            continue
        pos = sense.get("fl", "")
        shortdefs = sense.get("shortdef", [])
        if not shortdefs:
            continue
        defs = meanings_by_pos.setdefault(pos, [])
        for d in shortdefs:
            if len(defs) >= 2:
                break
            defs.append({"definition": _clean_mw_text(d), "example": ""})

    if not meanings_by_pos:
        return None

    meanings = [{"partOfSpeech": pos, "definitions": defs} for pos, defs in meanings_by_pos.items()]
    return {"word": word, "meanings": meanings, "source": "MW"}


def lookup_word_mw_synonyms(word, key):
    if not key:
        return []
    try:
        resp = requests.get(MW_THESAURUS_URL.format(word=word, key=key), timeout=10)
    except requests.RequestException:
        return []

    if resp.status_code != 200:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []
    if not data or isinstance(data[0], str):
        return []

    synonyms = set()
    for sense in data:
        hw = sense.get("hwi", {}).get("hw", "").replace("*", "")
        if hw.lower() != word.lower():
            continue
        for group in sense.get("meta", {}).get("syns", []):
            synonyms.update(group)

    return sorted(synonyms)[:8]


def wordnet_synonyms(word):
    synonyms = set()
    for ss in wordnet.synsets(word):
        for lemma in ss.lemmas():
            name = lemma.name().replace("_", " ")
            if name.lower() != word.lower():
                synonyms.add(name)
    return sorted(synonyms)[:8]


def lookup_word_wordnet(word):
    synsets = wordnet.synsets(word)
    if not synsets:
        return None

    meanings = []
    all_synonyms = set()
    seen_pos = {}

    for ss in synsets:
        pos = ss.pos()
        pos_name = {"n": "noun", "v": "verb", "a": "adjective", "r": "adverb", "s": "adjective"}.get(pos, pos)
        if pos_name not in seen_pos:
            seen_pos[pos_name] = []
        if len(seen_pos[pos_name]) < 2:
            seen_pos[pos_name].append({"definition": ss.definition(), "example": ""})
        for lemma in ss.lemmas():
            name = lemma.name().replace("_", " ")
            if name.lower() != word.lower():
                all_synonyms.add(name)

    for pos_name, defs in seen_pos.items():
        meanings.append({"partOfSpeech": pos_name, "definitions": defs})

    return {
        "word": word,
        "meanings": meanings,
        "synonyms": sorted(all_synonyms)[:8],
        "source": "WN",
    }


def lookup_word(word, dict_key, thes_key):
    result = lookup_word_mw_dictionary(word, dict_key)
    if result:
        synonyms = lookup_word_mw_synonyms(word, thes_key)
        if not synonyms:
            synonyms = wordnet_synonyms(word)
        result["synonyms"] = synonyms
        return result

    print("trying WordNet...", end=" ")
    return lookup_word_wordnet(word)


def build_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "WordHeading",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=BLUE,
        spaceAfter=3,
        spaceBefore=2,
    ))
    styles.add(ParagraphStyle(
        "PartOfSpeech",
        fontName="Helvetica-Oblique",
        fontSize=10,
        textColor=GRAY,
        spaceBefore=3,
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        "Def",
        fontName="Helvetica",
        fontSize=10,
        leftIndent=14,
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        "Example",
        fontName="Helvetica-Oblique",
        fontSize=10,
        textColor=GRAY,
        leftIndent=24,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "Synonyms",
        fontName="Helvetica",
        fontSize=9,
        textColor=GREEN,
        leftIndent=14,
        spaceBefore=2,
        spaceAfter=1,
    ))
    return styles


def escape(text):
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def build_pdf(entries, output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    styles = build_styles()
    story = []

    for i, entry in enumerate(entries):
        entry_parts = []
        word_display = entry["word"].capitalize()
        source = entry.get("source", "")
        source_tag = f' <font size="8" color="{SOURCE_COLOR}">[{source}]</font>' if source else ""
        entry_parts.append(Paragraph(word_display + source_tag, styles["WordHeading"]))

        for meaning in entry["meanings"]:
            pos = meaning["partOfSpeech"]
            entry_parts.append(Paragraph(pos, styles["PartOfSpeech"]))

            for defn in meaning["definitions"]:
                bullet = f"•  {escape(defn['definition'])}"
                entry_parts.append(Paragraph(bullet, styles["Def"]))
                if defn["example"]:
                    entry_parts.append(Paragraph(
                        f'"{escape(defn["example"])}"',
                        styles["Example"],
                    ))

        if entry["synonyms"]:
            syn_text = ", ".join(entry["synonyms"])
            entry_parts.append(Paragraph(
                f"<b>Synonyms:</b>  {escape(syn_text)}",
                styles["Synonyms"],
            ))

        story.append(KeepTogether(entry_parts))

        if i < len(entries) - 1:
            story.append(Spacer(1, 6))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=LIGHT_GRAY,
                spaceAfter=6, spaceBefore=2,
            ))

    doc.build(story)


def _first_definition(entry):
    for meaning in entry["meanings"]:
        if meaning["definitions"]:
            return meaning["definitions"][0]["definition"]
    return ""


def build_test_pdf(entries, output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    title_style = ParagraphStyle(
        "TestTitle",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=BLUE,
        spaceAfter=10,
        alignment=TA_LEFT,
    )
    header_style = ParagraphStyle(
        "TestHeader",
        fontName="Helvetica",
        fontSize=11,
        spaceAfter=14,
    )
    instruction_style = ParagraphStyle(
        "Instruction",
        fontName="Helvetica-Oblique",
        fontSize=10,
        textColor=GRAY,
        spaceAfter=16,
    )
    word_style = ParagraphStyle(
        "TestWord",
        fontName="Helvetica",
        fontSize=11,
    )
    def_style = ParagraphStyle(
        "TestDef",
        fontName="Helvetica",
        fontSize=10,
        spaceAfter=8,
    )

    story = []
    story.append(Paragraph("Vocabulary Matching Test", title_style))
    story.append(Paragraph(
        "Name: _______________________________&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "Date: ____________",
        header_style,
    ))
    story.append(Paragraph(
        "Instructions: Read each numbered definition on the page(s) after this word list. "
        "Write the number of the matching definition in the box next to each word.",
        instruction_style,
    ))

    rows = [[Paragraph(entry["word"].capitalize(), word_style), "", ""] for entry in entries]
    table = Table(rows, colWidths=[4.0 * inch, 0.2 * inch, 0.5 * inch], rowHeights=0.32 * inch)
    table_commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 8),
    ]
    for i in range(len(rows)):
        table_commands.append(("BOX", (0, i), (0, i), 0.75, GRAY))
        table_commands.append(("BOX", (2, i), (2, i), 0.75, BLACK))
    table.setStyle(TableStyle(table_commands))
    story.append(table)

    story.append(PageBreak())
    story.append(Paragraph("Definitions", title_style))
    story.append(Spacer(1, 8))

    shuffled_indices = list(range(len(entries)))
    random.shuffle(shuffled_indices)
    for display_num, orig_idx in enumerate(shuffled_indices, start=1):
        definition_text = _first_definition(entries[orig_idx])
        story.append(Paragraph(f"{display_num}.  {escape(definition_text)}", def_style))

    doc.build(story)


def main():
    parser = argparse.ArgumentParser(
        description="Look up words and create a dictionary PDF."
    )
    parser.add_argument("input_file", help="Text file with one word per line")
    parser.add_argument("-o", "--output", default="dictionary.pdf",
                        help="Output PDF filename (default: dictionary.pdf)")
    parser.add_argument("-t", "--test-output", default="test.pdf",
                        help="Output test paper PDF filename (default: test.pdf)")
    parser.add_argument("--cache-db", default=CACHE_DB_PATH,
                        help=f"Path to the local SQLite lookup cache (default: {CACHE_DB_PATH})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Don't read or write the local cache; always look up fresh")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Ignore cached entries and re-fetch, overwriting the cache")
    args = parser.parse_args()

    dict_key, thes_key = load_config()
    words = read_words(args.input_file)
    print(f"Looking up {len(words)} words...")

    conn = None if args.no_cache else init_cache_db(args.cache_db)

    entries = []
    for i, word in enumerate(words):
        print(f"  {word}...", end=" ")
        if conn is None:
            result, from_cache = lookup_word(word, dict_key, thes_key), False
        else:
            result, from_cache = lookup_word_cached(
                conn, word, dict_key, thes_key, refresh=args.refresh_cache
            )
        if result:
            entries.append(result)
            print("OK (cached)" if from_cache else "OK")
        else:
            print("skipped")
        if not from_cache and i < len(words) - 1:
            time.sleep(0.5)

    if conn is not None:
        conn.close()

    if not entries:
        print("No definitions found. PDF not created.")
        sys.exit(1)

    build_pdf(entries, args.output)
    build_test_pdf(entries, args.test_output)
    print(f"\nDone! {len(entries)} entries written to {args.output} and {args.test_output}")


if __name__ == "__main__":
    main()
