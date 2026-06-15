"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Model used for the two LLM-backed tools (free tier on Groq).
MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _llm(prompt: str, temperature: float = 0.7, max_tokens: int = 350) -> str:
    """Call the Groq chat model with a single user prompt and return the text.

    Raises on configuration or network/API errors — callers wrap this in a
    try/except so a failure becomes a graceful fallback string rather than a crash.
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokens we score relevance against — lowercased words from the description.
    query_tokens = [t for t in re.findall(r"[a-z0-9]+", (description or "").lower()) if t]

    size_filter = size.strip().lower() if size else None

    scored = []
    for item in listings:
        # ── price filter ──────────────────────────────────────────────
        if max_price is not None and item.get("price", 0) > max_price:
            continue

        # ── size filter (case-insensitive substring) ──────────────────
        if size_filter:
            item_size = str(item.get("size", "")).lower()
            # "One Size" pieces fit anyone, so they always pass the size gate.
            is_one_size = "one size" in item_size
            if not is_one_size and size_filter not in item_size:
                continue

        # ── relevance score (keyword overlap) ─────────────────────────
        haystack = " ".join(
            [
                item.get("title", ""),
                item.get("description", ""),
                item.get("category", ""),
                item.get("brand") or "",
                " ".join(item.get("style_tags", [])),
                " ".join(item.get("colors", [])),
            ]
        ).lower()
        haystack_tokens = set(re.findall(r"[a-z0-9]+", haystack))

        score = sum(1 for tok in query_tokens if tok in haystack_tokens)
        # Style tags are the most intentional signal, so weight them extra.
        tag_tokens = set(re.findall(r"[a-z0-9]+", " ".join(item.get("style_tags", [])).lower()))
        score += sum(1 for tok in query_tokens if tok in tag_tokens)

        # No keyword overlap at all → not a relevant match, drop it.
        if score == 0:
            continue

        scored.append((score, item))

    # Highest score first; stable for ties (preserves dataset order).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_name = new_item.get("title", "this piece")
    item_desc = _describe_item(new_item)
    items = (wardrobe or {}).get("items", [])

    if not items:
        # ── empty-wardrobe branch: general advice, no named pieces ──────
        prompt = (
            "You are a thrift-savvy personal stylist. A user is considering buying "
            f"this secondhand item:\n{item_desc}\n\n"
            "They have not entered any wardrobe yet, so you can't reference specific "
            "pieces they own. Give 2-3 sentences of general styling advice: what kinds "
            "of pieces pair well with it, what vibe it suits, and how to wear it. "
            "Be concrete about silhouettes and colors. Do not invent specific items "
            "they own."
        )
        fallback = (
            f"Since you haven't added your wardrobe yet, here's the general read on "
            f"{item_name}: it leans {', '.join(new_item.get('style_tags', [])) or 'versatile'}. "
            "Pair it with simple basics in neutral tones, balance the silhouette "
            "(fitted on top → relaxed on bottom, or vice versa), and let the piece be "
            "the focal point. Add your wardrobe for outfit ideas using pieces you own."
        )
    else:
        # ── wardrobe branch: name specific owned pieces ─────────────────
        closet = "\n".join(
            f"- {it.get('name', 'item')} ({it.get('category', '')}; "
            f"{', '.join(it.get('colors', []))}; {', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            "You are a thrift-savvy personal stylist. A user is considering buying "
            f"this secondhand item:\n{item_desc}\n\n"
            f"Here is their current wardrobe:\n{closet}\n\n"
            "Suggest 1-2 complete outfit combinations that pair the new item with "
            "SPECIFIC pieces named from their wardrobe above. Reference the pieces by "
            "name. Keep it to 3-4 sentences, concrete and wearable, mentioning shoes "
            "and a layer where it makes sense."
        )
        first = items[0].get("name", "your basics")
        fallback = (
            f"Pair {item_name} with {first}"
            + (f" and {items[1].get('name')}" if len(items) > 1 else "")
            + ". Keep the rest of the look simple so the new piece stands out, and "
            "finish with shoes that match the overall vibe."
        )

    try:
        return _llm(prompt, temperature=0.7)
    except Exception:
        # LLM/network/config failure → return a useful string, never crash.
        return fallback


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # ── guard: no outfit means nothing to caption ──────────────────────
    if not outfit or not outfit.strip():
        return (
            "Can't write a fit card without an outfit suggestion — run suggest_outfit "
            "first so there's a look to caption."
        )

    name = new_item.get("title", "this find")
    price = new_item.get("price")
    platform = new_item.get("platform", "")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        "Write a short, casual social-media caption (2-4 sentences) for a thrifted "
        "outfit, like a real OOTD post — not a product description.\n\n"
        f"Item: {name}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Rules: mention the item name, price, and platform naturally — once each. "
        "Capture the vibe in specific terms. Sound authentic and a little excited, "
        "lowercase-casual is fine, an emoji or two is fine. No hashtag spam."
    )

    # Higher temperature so the same input yields varied captions each run.
    try:
        return _llm(prompt, temperature=0.9, max_tokens=200)
    except Exception:
        vibe = ", ".join(new_item.get("style_tags", [])) or "easy everyday"
        return (
            f"thrifted this {name.lower()} off {platform} for {price_str} and honestly "
            f"obsessed 🫶 styled it for a {vibe} look — {outfit.strip()[:120]}"
        )


# ── shared helpers ────────────────────────────────────────────────────────────

def _describe_item(item: dict) -> str:
    """Compact one-block description of a listing for use inside LLM prompts."""
    return (
        f"- Title: {item.get('title', 'unknown')}\n"
        f"- Category: {item.get('category', 'unknown')}\n"
        f"- Colors: {', '.join(item.get('colors', [])) or 'n/a'}\n"
        f"- Style tags: {', '.join(item.get('style_tags', [])) or 'n/a'}\n"
        f"- Price: ${item.get('price', '?')} on {item.get('platform', 'unknown')}"
    )
