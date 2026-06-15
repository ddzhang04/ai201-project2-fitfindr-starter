"""
tests/test_tools.py

Tool-level tests. search_listings is pure Python and fully tested here. The two
LLM-backed tools are tested for their failure modes (the parts that must NOT call
the network), so the whole suite runs green without a GROQ_API_KEY.

Run with:  pytest tests/
"""

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_empty_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # every returned item is a full listing dict
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    # impossible constraints → empty list, no exception
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=30)
    assert all(item["price"] <= 30 for item in results)


def test_search_size_filter_substring():
    # "m" should match sizes like "S/M", "M/L" — case-insensitive substring
    results = search_listings("tee", size="M", max_price=None)
    assert all("m" in item["size"].lower() or "one size" in item["size"].lower()
               for item in results)


def test_search_ranks_best_first():
    # a more specific query should rank a clearly-matching item at the top
    results = search_listings("levi denim jeans", size=None, max_price=None)
    assert len(results) > 0
    assert "denim" in [t.lower() for t in results[0]["style_tags"]]


# ── create_fit_card failure mode (no network needed) ──────────────────────────

def test_fit_card_empty_outfit_returns_message():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("", item)
    assert isinstance(msg, str)
    assert msg.strip() != ""
    # it's the guard message, not a real caption, and definitely not an exception
    assert "without an outfit" in msg.lower()


def test_fit_card_whitespace_outfit_returns_message():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("   \n  ", item)
    assert "without an outfit" in msg.lower()


# ── suggest_outfit empty-wardrobe fallback (no network needed) ─────────────────

def test_suggest_outfit_empty_wardrobe_returns_string(monkeypatch):
    # Force the LLM call to fail so we exercise the graceful fallback path
    # without needing a real API key. Result must still be a useful non-empty string.
    import tools
    monkeypatch.setattr(tools, "_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no key")))

    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
