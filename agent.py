"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# Known size tokens we look for in a query. Ordered longest-first so "US 8" wins
# over a bare "8" and multi-letter sizes match before single letters.
_SIZE_PATTERNS = [
    r"us\s?\d+(?:\.\d+)?",     # US 8, US 8.5
    r"w\d{2}(?:\s?l\d{2})?",   # W30, W30 L30
    r"\b(?:xxs|xxl|xs|xl|s/m|m/l|l/xl|s|m|l)\b",
]


def parse_query(query: str) -> dict:
    """Extract description / size / max_price from a free-text query.

    Uses regex (documented choice in planning.md): a price phrase sets max_price,
    an explicit size phrase sets size, and the leftover words form the description.
    Anything not found is left as None so the corresponding filter is skipped.
    """
    text = query or ""
    lowered = text.lower()
    description = lowered

    # ── max_price: only when a price cue or $ is present, so "size 8" ──
    # isn't misread as a budget. Remove just the matched phrase from the desc.
    max_price = None
    price_phrase = re.compile(r"(?:under|below|less than|max|budget)\s*\$?\s*\d+(?:\.\d{1,2})?|\$\s*\d+(?:\.\d{1,2})?")
    price_cue = price_phrase.search(lowered)
    if price_cue:
        max_price = float(re.search(r"\d+(?:\.\d{1,2})?", price_cue.group(0)).group(0))
        description = description.replace(price_cue.group(0), " ")

    # ── size: "size M", "size US 8", "size 8", or a standalone token ───
    size = None
    size_label = re.search(
        r"size\s+(us\s?\d+(?:\.\d+)?|w\d{2}(?:\s?l\d{2})?|\d+(?:\.\d+)?|[a-z/]{1,4})\b",
        lowered,
    )
    if size_label:
        size = size_label.group(1).upper()
        description = description.replace(size_label.group(0), " ")
    else:
        for pat in _SIZE_PATTERNS:
            m = re.search(pat, lowered)
            if m:
                size = m.group(0).upper()
                description = description.replace(m.group(0), " ")
                break

    # ── description: leftover words, minus filler that adds no signal ──
    description = re.sub(
        r"\b(i'm|im|i am|looking|for|a|an|the|under|in|size|with|and|what|out|there|how|"
        r"would|style|it|my|that|to|find|me|want|need|some)\b",
        " ",
        description,
    )
    description = re.sub(r"[^a-z0-9\s]", " ", description)
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1 — fresh session for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2 — parse the query into search parameters.
    session["parsed"] = parse_query(query)
    parsed = session["parsed"]

    if not parsed["description"]:
        session["error"] = (
            "I couldn't tell what you're looking for. Try describing the item, "
            'e.g. "vintage graphic tee under $30, size M".'
        )
        return session

    # Step 3 — search. Branch on the result.
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    if not session["search_results"]:
        # No matches → tell the user what failed and what to adjust, then stop.
        # Do NOT call suggest_outfit with empty input.
        bits = [f'"{parsed["description"]}"']
        if parsed["size"]:
            bits.append(f"in size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:g}")
        session["error"] = (
            "No listings matched " + " ".join(bits) + ". "
            "Try removing the size filter, raising your budget, or using more "
            "general keywords."
        )
        return session

    # Step 4 — select the top-ranked item.
    session["selected_item"] = session["search_results"][0]

    # Step 5 — suggest an outfit using the selected item + wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6 — turn the suggestion into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7 — done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
