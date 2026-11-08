"""Tests for dictionary_app. No network or WordNet corpus needed: M-W calls are mocked."""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dictionary_app as app  # noqa: E402


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def mw_entry(hw, fl, shortdefs, stems=None, syns=None):
    meta = {"id": hw, "stems": stems if stems is not None else [hw]}
    if syns is not None:
        meta["syns"] = syns
    return {"meta": meta, "hwi": {"hw": hw}, "fl": fl, "shortdef": shortdefs}


@pytest.fixture
def fake_get(monkeypatch):
    """Route requests.get to canned responses keyed by (reference, word)."""
    responses = {}

    def _get(url, timeout=None):
        ref = "ithesaurus" if "/ithesaurus/" in url else "sd2"
        word = url.split("/json/")[1].split("?")[0]
        if (ref, word) not in responses:
            return FakeResponse([])
        resp = responses[(ref, word)]
        if isinstance(resp, Exception):
            raise resp
        return resp if isinstance(resp, FakeResponse) else FakeResponse(resp)

    monkeypatch.setattr(app.requests, "get", _get)
    return responses


# --- M-W text cleanup -------------------------------------------------------

def test_clean_mw_text_strips_markup():
    raw = "{bc}a {sx|haul||} or {d_link|pull|pull:1} {it}hard{/it}"
    assert app._clean_mw_text(raw) == "a haul or pull hard"


# --- Matching M-W entries to the list word ----------------------------------

def test_matching_entries_prefers_exact_headword():
    exact = mw_entry("critic", "noun", ["a judge"], stems=["critic", "critics"])
    other = mw_entry("critical", "adjective", ["finding fault"], stems=["critical", "critic"])
    assert app._mw_matching_entries([exact, other], "critic") == [exact]


def test_matching_entries_falls_back_to_stems_for_inflected_forms():
    haul = mw_entry("haul", "verb", ["to pull hard"], stems=["haul", "hauled", "hauling", "hauls"])
    unrelated = mw_entry("hall", "noun", ["a passage"], stems=["hall", "halls"])
    assert app._mw_matching_entries([haul, unrelated], "hauled") == [haul]


def test_matching_entries_strips_syllable_marks_and_ignores_case():
    entry = mw_entry("om*i*nous", "adjective", ["threatening"])
    assert app._mw_matching_entries([entry], "Ominous") == [entry]


def test_matching_entries_ignores_suggestion_strings():
    assert app._mw_matching_entries(["hall", "haul"], "hauled") == []


# --- Dictionary lookup ------------------------------------------------------

def test_mw_dictionary_exact_word(fake_get):
    fake_get[("sd2", "ominous")] = [
        mw_entry("om*i*nous", "adjective", ["{bc}showing that something bad may happen"]),
    ]
    result = app.lookup_word_mw_dictionary("ominous", "KEY")
    assert result == {
        "word": "ominous",
        "meanings": [{"partOfSpeech": "adjective", "definitions": [
            {"definition": "showing that something bad may happen", "example": ""},
        ]}],
        "source": "MW",
    }


def test_mw_dictionary_inflected_word_uses_base_entry(fake_get):
    fake_get[("sd2", "hauled")] = [
        mw_entry("haul", "verb", ["to pull or drag with effort", "to transport", "extra"],
                 stems=["haul", "hauled", "hauling", "hauls"]),
        mw_entry("haul", "noun", ["the act of pulling"], stems=["haul", "hauls"]),
    ]
    result = app.lookup_word_mw_dictionary("hauled", "KEY")
    assert result["word"] == "hauled"
    assert result["source"] == "MW"
    # Only the verb entry lists "hauled" as a stem; max 2 definitions per part of speech.
    assert result["meanings"] == [{"partOfSpeech": "verb", "definitions": [
        {"definition": "to pull or drag with effort", "example": ""},
        {"definition": "to transport", "example": ""},
    ]}]


def test_mw_dictionary_combines_definitions_by_part_of_speech(fake_get):
    fake_get[("sd2", "dispute")] = [
        mw_entry("dispute", "verb", ["to argue about"]),
        mw_entry("dispute", "noun", ["an argument"]),
        mw_entry("dispute", "verb", ["to question the truth of", "a third one"]),
    ]
    result = app.lookup_word_mw_dictionary("dispute", "KEY")
    assert [(m["partOfSpeech"], [d["definition"] for d in m["definitions"]])
            for m in result["meanings"]] == [
        ("verb", ["to argue about", "to question the truth of"]),
        ("noun", ["an argument"]),
    ]


@pytest.mark.parametrize("response", [
    [],                               # nothing found
    ["haul", "hall"],                 # spelling suggestions only
    FakeResponse(None, status_code=500),
    requests.ConnectionError("down"),
])
def test_mw_dictionary_returns_none_when_not_found(fake_get, response):
    fake_get[("sd2", "zzz")] = response
    assert app.lookup_word_mw_dictionary("zzz", "KEY") is None


def test_mw_dictionary_without_key_skips_network(monkeypatch):
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: pytest.fail("should not call"))
    assert app.lookup_word_mw_dictionary("ominous", "") is None


# --- Thesaurus lookup -------------------------------------------------------

def test_mw_synonyms_inflected_word(fake_get):
    fake_get[("ithesaurus", "hauled")] = [
        mw_entry("haul", "verb", ["to pull"], stems=["haul", "hauled"],
                 syns=[["drag", "pull"], ["tow", "lug"]]),
    ]
    assert app.lookup_word_mw_synonyms("hauled", "KEY") == ["drag", "lug", "pull", "tow"]


def test_mw_synonyms_capped_at_eight(fake_get):
    syns = [[f"word{i}" for i in range(12)]]
    fake_get[("ithesaurus", "big")] = [mw_entry("big", "adjective", ["large"], syns=syns)]
    assert len(app.lookup_word_mw_synonyms("big", "KEY")) == 8


# --- Lookup orchestration ---------------------------------------------------

def test_lookup_word_uses_mw_and_falls_back_to_wordnet_synonyms(fake_get, monkeypatch):
    fake_get[("sd2", "uproar")] = [mw_entry("up*roar", "noun", ["a noisy disturbance"])]
    monkeypatch.setattr(app, "wordnet_synonyms", lambda w: ["tumult"])
    result = app.lookup_word("uproar", "KEY", "KEY")
    assert result["source"] == "MW"
    assert result["synonyms"] == ["tumult"]


def test_lookup_word_falls_back_to_wordnet(fake_get, monkeypatch):
    wn_entry = {"word": "parlour", "meanings": [], "synonyms": [], "source": "WN"}
    monkeypatch.setattr(app, "lookup_word_wordnet", lambda w: wn_entry)
    assert app.lookup_word("parlour", "KEY", "KEY") is wn_entry


# --- Word reader ------------------------------------------------------------

def test_read_words_dedupes_lowercases_and_sorts(tmp_path):
    f = tmp_path / "words.txt"
    f.write_text("Rift\n\n  banter \nrift\nantics\n", encoding="utf-8")
    assert app.read_words(str(f)) == ["antics", "banter", "rift"]


def test_read_words_empty_file_exits(tmp_path):
    f = tmp_path / "words.txt"
    f.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(SystemExit):
        app.read_words(str(f))


# --- Cache ------------------------------------------------------------------

def sample_entry(word="rift", source="MW", definition="a crack"):
    return {
        "word": word,
        "meanings": [{"partOfSpeech": "noun", "definitions": [
            {"definition": definition, "example": ""},
            {"definition": "a break in friendship", "example": "a rift between friends"},
        ]}],
        "synonyms": ["crack", "split"],
        "source": source,
    }


def test_cache_round_trip(tmp_path):
    conn = app.init_cache_db(str(tmp_path / "cache.db"))
    app.cache_put(conn, sample_entry())
    assert app.cache_get(conn, "rift") == sample_entry()
    assert app.cache_get(conn, "missing") is None


def test_cache_prefers_mw_over_wordnet(tmp_path):
    conn = app.init_cache_db(str(tmp_path / "cache.db"))
    app.cache_put(conn, sample_entry(source="WN", definition="wn def"))
    app.cache_put(conn, sample_entry(source="MW", definition="mw def"))
    assert app.cache_get(conn, "rift")["source"] == "MW"
    assert app.cache_get(conn, "rift", source="WN")["meanings"][0]["definitions"][0]["definition"] == "wn def"


def test_cache_put_replaces_instead_of_duplicating(tmp_path):
    conn = app.init_cache_db(str(tmp_path / "cache.db"))
    app.cache_put(conn, sample_entry(definition="old"))
    app.cache_put(conn, sample_entry(definition="new"))
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    assert app.cache_get(conn, "rift")["meanings"][0]["definitions"][0]["definition"] == "new"


def test_lookup_word_cached_skips_lookup_on_hit(tmp_path, monkeypatch):
    conn = app.init_cache_db(str(tmp_path / "cache.db"))
    app.cache_put(conn, sample_entry())
    monkeypatch.setattr(app, "lookup_word", lambda *a: pytest.fail("should use cache"))
    result, from_cache = app.lookup_word_cached(conn, "rift", "", "")
    assert from_cache and result["word"] == "rift"


def test_lookup_word_cached_refresh_overwrites(tmp_path, monkeypatch):
    conn = app.init_cache_db(str(tmp_path / "cache.db"))
    app.cache_put(conn, sample_entry(definition="old"))
    monkeypatch.setattr(app, "lookup_word", lambda *a: sample_entry(definition="fresh"))
    result, from_cache = app.lookup_word_cached(conn, "rift", "", "", refresh=True)
    assert not from_cache
    assert app.cache_get(conn, "rift")["meanings"][0]["definitions"][0]["definition"] == "fresh"


# --- Test paper / answer key ------------------------------------------------

def test_answer_numbers_inverts_shuffle():
    # Definition 1 shown is entry 2's, definition 2 is entry 0's, definition 3 is entry 1's.
    assert app._answer_numbers([2, 0, 1]) == [2, 3, 1]


def test_first_definition_skips_empty_meanings():
    entry = {"meanings": [
        {"partOfSpeech": "noun", "definitions": []},
        {"partOfSpeech": "verb", "definitions": [{"definition": "to split", "example": ""}]},
    ]}
    assert app._first_definition(entry) == "to split"


def test_pdfs_build(tmp_path):
    entries = [sample_entry("antics"), sample_entry("banter"), sample_entry("rift & <co>")]
    shuffled = app.shuffle_definition_order(entries)
    assert sorted(shuffled) == [0, 1, 2]
    app.build_pdf(entries, str(tmp_path / "dict.pdf"))
    app.build_test_pdf(entries, str(tmp_path / "test.pdf"), shuffled)
    app.build_answer_key_pdf(entries, str(tmp_path / "key.pdf"), shuffled)
    for name in ["dict.pdf", "test.pdf", "key.pdf"]:
        assert (tmp_path / name).read_bytes().startswith(b"%PDF")
