# FitFindr — planning.md

> Written before implementation. This spec and the agent diagram are what I used to
> direct AI tooling to generate the implementation, and what I verified the code against.

FitFindr is a multi-tool AI agent for thrifting. A user describes what they want in
natural language; the agent searches a mock listings dataset, picks the best match,
suggests how to wear it against the user's existing wardrobe, and writes a shareable
"fit card" caption. It calls tools in response to what each previous step returned —
if the search comes back empty, it stops and tells the user instead of barreling into
the styling tools with nothing.

---

## Tools

### Tool 1: search_listings

**What it does:**
Filters the 40-item mock listings dataset by an optional size and price ceiling, then
scores the survivors by keyword overlap against the user's free-text description and
returns the matches ranked best-first.

**Input parameters:**
- `description` (str): Free-text keywords describing the wanted item, e.g. `"vintage graphic tee"`. Tokenized and matched against each listing's title, description, style_tags, category, colors, and brand.
- `size` (str | None): Size to filter by, or `None` to skip size filtering. Matching is case-insensitive substring (`"m"` matches `"S/M"`, `"8"` matches `"US 8"`). Listings whose size is `"One Size"`/`"One Size (adjustable)"` always pass the size filter.
- `max_price` (float | None): Inclusive price ceiling, or `None` to skip price filtering.

**What it returns:**
`list[dict]` — the matching listing dicts (full original fields: `id`, `title`,
`description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`,
`brand`, `platform`), sorted by descending keyword-overlap score. Listings with a
score of 0 (no keyword overlap at all) are dropped. Returns `[]` when nothing matches.

**What happens if it fails or returns nothing:**
Returns an empty list — never raises. The planning loop detects `[]`, writes a specific
error into the session (naming the description/size/price that produced no hits and
suggesting the user loosen a constraint), and returns early **without** calling
`suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Given the chosen thrifted item and the user's wardrobe, asks the LLM for 1–2 concrete
outfit combinations that pair the new item with specific pieces the user already owns.

**Input parameters:**
- `new_item` (dict): A listing dict (the item the user is considering) — the tool uses its title, category, colors, and style_tags in the prompt.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ {name, category, colors, style_tags, notes}, ... ]}`. May have an empty `items` list — handled explicitly.

**What it returns:**
`str` — a non-empty styling suggestion. When the wardrobe has items, the suggestion
names specific owned pieces ("pair it with your wide-leg khaki trousers and chunky
white sneakers"). When the wardrobe is empty, it returns general styling advice for
the item (what kinds of pieces and vibe pair well) instead.

**What happens if it fails or returns nothing:**
- Empty wardrobe → branch to a "general advice" prompt rather than naming nonexistent pieces.
- LLM/network error → caught and returned as a readable fallback string (a non-LLM templated suggestion built from the item's own style_tags) so the agent stays useful instead of crashing.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion plus the item details into a short, casual, shareable
caption — the kind of thing someone captions an OOTD post with.

**Input parameters:**
- `outfit` (str): The suggestion string from `suggest_outfit`.
- `new_item` (dict): The listing dict (used for item name, price, platform).

**What it returns:**
`str` — a 2–4 sentence caption that mentions the item name, price, and platform once
each, captures the vibe in specific terms, reads like a real post (not a product blurb),
and varies between runs (LLM temperature is raised to ~0.9 so identical input still
produces different captions).

**What happens if it fails or returns nothing:**
- Empty / whitespace-only `outfit` → returns a descriptive error message string (`"Can't write a fit card without an outfit suggestion..."`), never raises.
- LLM/network error → caught and returned as a templated fallback caption built from the item fields.

---

### Additional Tools (if any)

None for the required submission. Candidate stretch tool (`estimate_price_fairness`)
is noted but not implemented; planning.md will be updated before building it.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed forward sequence (search → suggest → fit card) **gated by
conditionals on what each step returns** — it is not "call all three unconditionally."

1. Parse the query into `description`, `size`, `max_price` (regex: a `$NN` / `under NN`
   pattern → `max_price`; a `size X` pattern → `size`; the remaining words →
   `description`). Store in `session["parsed"]`.
2. Call `search_listings(description, size, max_price)`. Store in `session["search_results"]`.
   - **Branch:** if the result is empty → set `session["error"]` to a specific message
     and `return` immediately. `suggest_outfit` and `create_fit_card` are **not** called.
3. Otherwise set `session["selected_item"] = search_results[0]` (highest-scored match).
4. Call `suggest_outfit(selected_item, wardrobe)`. Store in `session["outfit_suggestion"]`.
5. Call `create_fit_card(outfit_suggestion, selected_item)`. Store in `session["fit_card"]`.
6. Return the session.

The agent's behavior therefore differs by input: an impossible query terminates after
step 2 with an error and `fit_card == None`; a matchable query runs the full chain. The
item chosen in step 3 flows into steps 4 and 5 without the user re-entering anything.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session`) is the one source of truth for the
interaction. Each step writes its output to a named key, and later steps read from the
session rather than from re-prompting the user:

- `query` — original text → read by the parse step
- `parsed` — `{description, size, max_price}` → read by `search_listings`
- `search_results` — output of `search_listings` → read to pick the selected item
- `selected_item` — `search_results[0]` → passed into **both** `suggest_outfit` and `create_fit_card`
- `outfit_suggestion` — output of `suggest_outfit` → passed into `create_fit_card`
- `fit_card` — output of `create_fit_card` → final user-facing result
- `error` — set only on early termination; when non-`None` the output fields stay `None`

`run_agent` returns the completed session, so the caller (CLI or Gradio `app.py`) can
inspect exactly what each tool produced.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]`; loop sets a specific `session["error"]` ("No listings matched 'X' under $Y in size Z — try removing the size filter or raising your budget") and returns early without calling the styling tools. |
| suggest_outfit | Wardrobe is empty | Detects `wardrobe["items"] == []` and switches to a general-styling prompt, returning broad advice for the item rather than naming pieces the user doesn't own. (LLM errors fall back to a templated suggestion from the item's style_tags.) |
| create_fit_card | Outfit input is missing or incomplete | Guards against empty/whitespace `outfit` and returns a descriptive error string instead of raising. (LLM errors fall back to a templated caption built from the item fields.) |

---

## Architecture

```
User query ("vintage graphic tee under $30, size M")
   |
   v
Planning Loop -----------------------------------------------------+
   |                                                               |
   |  parse query -> session["parsed"] = {description, size, max_price}
   |                                                               |
   +--> search_listings(description, size, max_price)             |
   |        |  results == []                                      |
   |        +----> [ERROR] session["error"] = "No listings..."  --+--> return session (fit_card = None)
   |        |                                                      |
   |        |  results = [item, ...]                               |
   |        v                                                      |
   |     Session: selected_item = results[0]                       |
   |        |                                                      |
   +--> suggest_outfit(selected_item, wardrobe)                    |
   |        |   (empty wardrobe -> general advice branch)          |
   |        v                                                      |
   |     Session: outfit_suggestion = "..."                        |
   |        |                                                      |
   +--> create_fit_card(outfit_suggestion, selected_item)          |
   |        |   (empty outfit -> error-string guard)               |
   |        v                                                      |
   |     Session: fit_card = "..."                                 |
   |        |                                                      |
   v        v                                                      |
Return session <-------------------------------------------------- +
```

All tool I/O passes through the `session` dict (State / Session store). The single error
branch is after `search_listings`: when it returns `[]` the flow terminates early and the
styling tools never run.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**
I used Claude (Claude Code) as the implementation assistant. For each tool I handed it
the corresponding Tool block above — exact parameter names/types, the return contract,
and the failure mode — plus the data shape from `listings.json` / `wardrobe_schema.json`.
- `search_listings`: asked for a pure-Python keyword-overlap scorer using `load_listings()`
  from `utils/data_loader.py`, filtering by all three params and handling the empty case.
  **Verification:** ran the three pytest cases (returns results, empty-results == `[]`,
  price filter all `<= max_price`) plus manual queries before trusting it.
- `suggest_outfit` / `create_fit_card`: gave Claude the Tool 2/3 blocks and required an
  explicit empty-wardrobe branch (Tool 2) and empty-outfit guard (Tool 3), with a
  try/except fallback so an LLM/network error returns a string instead of raising.
  **Verification:** triggered each failure mode from the terminal and confirmed a string
  came back, and ran `create_fit_card` repeatedly on the same input to confirm variation.

**Milestone 4 — Planning loop and state management:**
I gave Claude the Architecture diagram and the Planning Loop + State Management sections
and asked it to implement `run_agent()` matching the numbered branch logic. **Verification:**
I checked that the generated loop branches on the `search_listings` result (early return
on `[]`), writes every value into the `session` dict rather than using locals, and never
calls `suggest_outfit` with empty input — then ran both the happy path and the
no-results path and inspected the session.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear
baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — parse + search.**
The loop parses `max_price = 30.0` (from "under $30"), `size = None` (no explicit size
given), and `description = "vintage graphic tee"`. It calls
`search_listings("vintage graphic tee", None, 30.0)`. The scorer ranks the Y2K Baby Tee
(style_tags include `graphic tee`, `vintage`; price $18) at the top. `session["search_results"]`
holds the ranked list; `session["selected_item"]` becomes that top listing.

**Step 2 — suggest outfit.**
With a non-empty result, the loop calls `suggest_outfit(selected_item, wardrobe)`. The
example wardrobe has baggy jeans, wide-leg trousers, chunky white sneakers, etc., so the
LLM returns something like: "Tuck the front of the baby tee into your baggy straight-leg
jeans and finish with the chunky white sneakers — add the black denim jacket if it's
cool out." Stored in `session["outfit_suggestion"]`.

**Step 3 — create fit card.**
The loop calls `create_fit_card(outfit_suggestion, selected_item)`, which returns a
caption like: "found this y2k butterfly baby tee on depop for $18 and it's already my
favorite 🦋 styled it with my baggy jeans + chunky sneakers for that effortless 2000s
look." Stored in `session["fit_card"]`.

**Final output to user:**
The top listing details, the outfit idea, and the fit card — three panels in the Gradio
app. If step 1 had returned `[]` (e.g. "designer ballgown size XXS under $5"), the user
would instead see only the error message and the styling steps would never run.
