# FitFindr 🛍️

A multi-tool AI agent for thrifting. You describe what you want in plain language;
FitFindr searches a mock secondhand-listings dataset, picks the best match, suggests how
to wear it against your existing wardrobe, and writes a short shareable "fit card"
caption — calling each tool in response to what the previous step returned, and stopping
gracefully when something comes back empty.

> Built for AI201 Project 2. Planning and design notes live in [`planning.md`](planning.md).

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: source .venv/Scripts/activate
pip install -r requirements.txt
```

Create a `.env` in the project root (template in [`.env.example`](.env.example)). Get a
free key at [console.groq.com](https://console.groq.com):

```
GROQ_API_KEY=your_key_here
```

Run it:

```bash
python app.py          # Gradio UI at http://localhost:7860 (check terminal for port)
python agent.py        # CLI: runs the happy path + the no-results path
pytest tests/          # tool-level tests
```

> **No key?** `search_listings` and every failure mode work without one. The two
> LLM-backed tools (`suggest_outfit`, `create_fit_card`) detect a missing key / network
> error and return a templated fallback string instead of crashing, so the agent still
> completes end-to-end — just with simpler styling text.

---

## Tool Inventory

Signatures below match `tools.py` exactly.

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`
- **Inputs:**
  - `description` (str): free-text keywords (e.g. `"vintage graphic tee"`), tokenized and matched against each listing's title, description, category, brand, style_tags, and colors.
  - `size` (str | None): size to filter by, case-insensitive **substring** match (`"m"` matches `"S/M"`, `"8"` matches `"US 8"`); `"One Size"` listings always pass. `None` skips size filtering.
  - `max_price` (float | None): inclusive price ceiling; `None` skips price filtering.
- **Output:** `list[dict]` of full listing dicts (`id, title, description, category, style_tags, size, condition, price, colors, brand, platform`), sorted by descending keyword-overlap score (style-tag hits weighted double). Listings with zero keyword overlap are dropped. Returns `[]` when nothing matches.
- **Purpose:** find and rank relevant secondhand listings for the user's request.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`
- **Inputs:**
  - `new_item` (dict): a listing dict (the item being considered).
  - `wardrobe` (dict): `{"items": [...]}` of owned pieces (`name, category, colors, style_tags, notes`); may be empty.
- **Output:** `str` — 1–2 concrete outfit ideas. With a wardrobe, it names specific owned pieces; with an empty wardrobe, it gives general styling advice for the item.
- **Purpose:** turn a found item into wearable outfit suggestions grounded in what the user already owns.

### `create_fit_card(outfit: str, new_item: dict) -> str`
- **Inputs:**
  - `outfit` (str): the suggestion string from `suggest_outfit`.
  - `new_item` (dict): the listing dict (used for name, price, platform).
- **Output:** `str` — a 2–4 sentence casual caption that mentions the item name, price, and platform once each. Runs at high LLM temperature so repeated calls vary.
- **Purpose:** produce a shareable, authentic-sounding OOTD caption for the thrifted find.

---

## How the Planning Loop Works

`run_agent(query, wardrobe)` in [`agent.py`](agent.py) is a forward sequence
(**search → suggest → fit card**) **gated by conditionals on what each step returns** — it
does not call all three tools unconditionally.

1. **Parse** the query with regex (`parse_query`): a price phrase (`under $30`, `$30`)
   sets `max_price`; a size phrase (`size M`, `size 8`, `size W30`) or a standalone size
   token sets `size`; the leftover words become `description`.
2. **Guard:** if no description survives parsing, set an error and return early.
3. **Search:** call `search_listings(description, size, max_price)`.
   - **Branch — the one decision point:** if the result is `[]`, write a specific error
     into the session and **return immediately**. `suggest_outfit` and `create_fit_card`
     are never called with empty input.
4. **Select** `search_results[0]` (highest-scored match) as `selected_item`.
5. **Suggest** an outfit from `selected_item` + `wardrobe`.
6. **Fit card** from the outfit suggestion + `selected_item`.
7. **Return** the completed session.

Behavior therefore changes with the input: an impossible query (`"designer ballgown size
XXS under $5"`) stops after step 3 with `fit_card == None`; a matchable query runs the
full chain.

---

## State Management

A single `session` dict (built by `_new_session`) is the source of truth for one
interaction. Each step writes its output to a named key; later steps read from the
session rather than re-prompting:

| Key | Written by | Read by |
|-----|-----------|---------|
| `query` | caller | parse step |
| `parsed` | parse step | `search_listings` |
| `search_results` | `search_listings` | item selection |
| `selected_item` | selection (`results[0]`) | **both** `suggest_outfit` and `create_fit_card` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | final output |
| `error` | any early-exit branch | caller (UI/CLI) |

`run_agent` returns the session, so `app.py` and the CLI inspect exactly what each tool
produced. The item found by `search_listings` flows into `suggest_outfit` and
`create_fit_card` with no re-entry — visible in the demo when the same listing's title
appears in the outfit idea and the fit card.

---

## Error Handling

Every tool owns its failure mode and returns a value (never raises into the loop).

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings match | Returns `[]`; the loop sets a specific `session["error"]` and returns early without calling the styling tools. |
| `suggest_outfit` | Empty wardrobe | Detects `wardrobe["items"] == []` and switches to a general-advice prompt instead of naming pieces the user doesn't own. LLM/network errors fall back to a templated suggestion. |
| `create_fit_card` | Empty/whitespace `outfit` | Returns a descriptive guard string. LLM/network errors fall back to a templated caption. |

**Concrete example from testing** (Milestone 5, run with no/invalid key to force the path):

```text
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]

$ python -c "from tools import search_listings, create_fit_card;
  r = search_listings('vintage graphic tee', size=None, max_price=50);
  print(create_fit_card('', r[0]))"
Can't write a fit card without an outfit suggestion — run suggest_outfit first so there's a look to caption.
```

And the full agent on the impossible query returns, in `session["error"]`:

```text
No listings matched "designer ballgown" in size XXS under $5. Try removing the size
filter, raising your budget, or using more general keywords.
```

— with `session["fit_card"]` left as `None`, proving the styling tools were skipped.

---

## Interaction Walkthrough

**User query:** `"I'm looking for a vintage graphic tee under $30. I mostly wear baggy
jeans and chunky sneakers. What's out there and how would I style it?"` (Example wardrobe)

**Step 1 — `search_listings`**
- Input: `parse_query` extracts `description="vintage graphic tee"`, `size=None`, `max_price=30.0`, so the loop calls `search_listings("vintage graphic tee", None, 30.0)`.
- Why: the agent always needs a concrete item before it can style anything.
- Output: ranked matches; the **Y2K Baby Tee — Butterfly Print** ($18, depop; tags include `graphic tee`, `vintage`) tops the list and becomes `selected_item`.

**Step 2 — `suggest_outfit`**
- Input: `selected_item` + the example wardrobe (baggy jeans, wide-leg trousers, chunky white sneakers, denim jacket…).
- Why: search returned a non-empty result, so the loop proceeds to styling — using the item from Step 1 without re-asking the user.
- Output: a suggestion naming owned pieces, e.g. *"Tuck the baby tee into your baggy straight-leg jeans and finish with the chunky white sneakers; layer the black denim jacket if it's cool."*

**Step 3 — `create_fit_card`**
- Input: the Step 2 suggestion + `selected_item`.
- Why: final step — package the look as something shareable.
- Output: e.g. *"found this y2k butterfly baby tee on depop for $18 and it's already my favorite 🦋 styled with my baggy jeans + chunky sneakers for that effortless 2000s look."*

**Final output to user:** three panels — the top listing, the outfit idea, and the fit
card. Had Step 1 returned `[]`, the user would see only the error message and Steps 2–3
would never run.

---

## Spec Reflection

**One way `planning.md` helped during implementation:**
Writing the Error Handling table and the architecture diagram *before* coding forced me to
decide the single branch point up front — that `search_listings` returning `[]` is the
only place the loop terminates early, and that the styling tools must never receive empty
input. Implementing `run_agent` was then almost transcription: the numbered steps and the
early-return branch came straight from the spec, and I didn't have to retrofit error
handling afterward.

**One divergence from my spec, and why:**
The spec described `suggest_outfit` and `create_fit_card` as pure LLM calls. In
implementation I added a `try/except` fallback to each so an LLM/network/missing-key error
returns a templated string built from the item's own fields rather than raising. The spec
only required handling the *empty-input* failure modes, but a thrown exception from the
network would crash the planning loop just as badly as bad input — so I treated "the LLM
call itself fails" as a fourth failure mode worth covering. This also lets the whole agent
run end-to-end without an API key for grading/testing.

---

## AI Usage

**Instance 1 — implementing `search_listings`.**
I gave Claude (via Claude Code) the Tool 1 block from `planning.md` (exact params, the
"drop score-0 listings, sort descending" return contract, and the empty-result rule) plus
the real field shape from `listings.json`. It produced a keyword-overlap scorer. **What I
changed:** I had it weight style-tag matches double (the dataset's `style_tags` are the
most intentional relevance signal), and I added the `"One Size"`-always-passes rule to the
size filter after noticing the dataset has sizes like `"One Size (adjustable)"` that a
literal substring match on `"m"` would wrongly exclude.

**Instance 2 — implementing the planning loop in `run_agent`.**
I gave Claude the Architecture diagram and the Planning Loop + State Management sections
and asked it to match the numbered branch logic. **What I verified/overrode:** I checked
that the generated loop branches on the `search_listings` result (early return on `[]`),
writes every value into the `session` dict rather than locals, and never calls
`suggest_outfit` with empty input. I also tightened the regex query parser so a number
like `"90s"` isn't misread as a price and a bare `"size 8"` is captured — the first draft
mishandled both.
