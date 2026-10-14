# Campus Customs — Storefront + Shopping Assistant

MGT 409 E1, Homework 4. A Yale merchandise storefront with a chatbot that answers questions about
products, prices, and stock from a local database, puts matching products on the page, remembers
signed-in shoppers, speaks English and Spanish, and sends the store owner inventory notes.

- **Front end:** React 19 + Vite + TypeScript (`frontend/`)
- **Back end:** Python 3.14 + FastAPI (`backend/`)
- **Brains:** two PydanticAI agents (`backend/agent.py`, `backend/inventory_agent.py`) reached
  through the Portkey gateway to OpenAI
- **Data:** SQLite database and product photos provided with the assignment (`data/`)
- **Repository:** <https://github.com/AMR6958-coder/campus-customs-hw4> (public; the data, the real `.env`, and archives are not committed)

## What it does

- Browse 102 products in a yale.edu-style design; each product opens a detail page with a real
  per-size stock picker.
- Create an account and log in (passwords stored as PBKDF2 hashes, signed session cookie).
- Chat in the bottom-right widget. Matching products appear as cards in the reply and in a
  "Picked for you" strip at the top of the page; clicking a card opens the product.
- Prices and stock come from the database through tools, and an output validator rejects any reply
  that quotes a price or product the tools did not return.
- Signed-in shoppers are greeted by name and their conversation is saved and restored.
- "Do you have this in pink?" on a product page refers to that product.
- English or Spanish, by selector or automatically from the message.
- A browser cart and a demo checkout (the "Place order" button is intentionally disabled).
- Views, clicks, and add-to-carts are tracked; the owner's Inventory tab shows low stock and
  activity, and a second agent writes reorder / do-not-reorder notes.
- Every agent run is appended to an audit trail; a reproducible operational test with screenshots
  covers the whole site.

## How the system works

```
 Browser (React, :5173)  ──/api, /media──►  FastAPI (:8000)  ──►  SQLite data/campus_customs.db
   pages · contexts · ChatWidget             main.py, auth.py, tools.py        + data/products/*.jpg
                                             │
                                             ├─► agent.py  (shop assistant, 6 tools, validator)
                                             ├─► inventory_agent.py (inventory assistant, 3 tools)
                                             └─► audit_trail.py ─► output/audit_trail.json
                                                        │
                                                        ▼
                                              Portkey gateway ─► OpenAI gpt-5.6-luna
```

**A chat turn, step by step**

1. The widget posts the message, the product id of the current page (if any), the language
   selection, and (for guests) the conversation so far to `POST /api/chat`.
2. The server loads a signed-in shopper's saved history, builds the agent's dependencies
   (database connection, user, page product, recent products, language), and runs the agent.
3. The agent's only knowledge of the store comes from six tools that read the database:
   `search_products`, `get_product_details`, `check_stock`, `get_current_product`,
   `list_garment_types`, `get_shopper_profile`. The instructions live in
   `backend/prompts/prompt.md` and are re-read whenever the file changes.
4. The agent returns text plus product ids. The output validator checks that every id exists,
   every dollar amount came from a tool result (or the page product), a lookup happened when the
   question needed one, and the reply is in the required language; otherwise the model is asked to
   try again.
5. The server re-reads the product ids from the database, saves the turn for a signed-in shopper,
   and returns the reply, full product cards, and the user. The widget shows the reply; the strip
   shows the cards.
6. The whole loop (tool calls, arguments, result previews, retries, tokens, timing) is appended as
   one record to `output/audit_trail.json`.

**The inventory loop.** The page posts `view`, `click`, and `add_to_cart` events to
`POST /api/events`. `backend/inventory.py` applies the rules: a size at or below 20% of par (25
units, so 5 or fewer) is flagged for reorder; a product with five or more views or clicks and no
add-to-cart in 30 days is flagged do-not-reorder. The owner opens the Inventory tab and clicks
"Run inventory review"; the inventory assistant reads the report and the open notes and sends up to
ten notes of each kind through a tool that refuses unflagged products, fake ids, and duplicates.

**Accounts.** `POST /api/auth/register` stores `pbkdf2_sha256$salt$hash` (PBKDF2-HMAC-SHA256,
120,000 iterations); login verifies with a constant-time compare and sets the signed
`campus_session` cookie; the owner is the account named by `OWNER_EMAIL` (default: the test user).

**Audit trail.** `output/audit_trail.json` is append-only JSON Lines (one record per line). It is
written by `backend/audit_trail.py` from inside both agents' run functions, on success and on
failure. See "Reading the audit trail" below.

## Folder map

| Path | What is there |
|---|---|
| `backend/main.py` | FastAPI app: products, images, chat, history, events, owner routes |
| `backend/auth.py`, `security.py`, `db.py` | Accounts and sessions, password hashing, database connection |
| `backend/models.py`, `tools.py` | Pydantic schemas; catalogue and stock lookups shared by routes and agents |
| `backend/agent.py`, `prompts/prompt.md` | The shopping assistant and its instructions |
| `backend/inventory.py`, `inventory_agent.py`, `prompts/inventory_prompt.md` | Tracking tables, rules, and the inventory assistant |
| `backend/audit_trail.py` | Append-only audit trail of agent runs |
| `backend/app_check.py`, `reset_demo_data.py` | Operational test; demo-data reset |
| `frontend/src/pages/` | Home, Products, Product detail, About, Cart, Checkout, Owner, Log In, Create Account |
| `frontend/src/components/` | NavBar, ProductCard, RecommendedStrip, ChatWidget |
| `frontend/src/*Context.tsx` | Auth, Cart (browser storage), Picks (cards from the chat) |
| `frontend/src/index.css` | The yale.edu-style design tokens and styles |
| `data/` | The assignment's database and photos |
| `output/` | Design record (`harness.md`), test report (`app_check.html` + screenshots), audit trail, summaries |

## Data (not in the repository)

The instructor's database and product photos are not committed. Before running, put them in
place so the folder looks like this:

```
data/campus_customs.db
data/products/<product-id>.jpg   (102 photos)
```

They come from the `data.zip` provided with the assignment: unzip it into `data/`. The back end
reports `database_found` on `GET /api/health`, and `output/harness.md` section 1 describes the
tables.

## Running locally

You need Node 20+ and Python 3.14. Open two terminals from this folder.

**Terminal 1: back end**

```
cd backend
.venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

If `backend/.venv` does not exist yet, create it first:

```
py -3.14 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
```

The back end also needs a `backend/.env` file. Copy `backend/.env.example` to `backend/.env` and
fill in:

- `SESSION_SECRET`: a long random string used to sign login cookies, for example the output of
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- `PORTKEY_API_KEY`: the Portkey gateway key the course provides (it routes to OpenAI).
- `OPENAI_MODEL` and `PORTKEY_BASE_URL`: already filled in with the course defaults.
- `OWNER_EMAIL` (optional): which account sees the Inventory tab; defaults to the test user.
- `INVENTORY_PAR_LEVEL`, `INVENTORY_REORDER_THRESHOLD`, `INVENTORY_WINDOW_DAYS`, `INVENTORY_MIN_VIEWS`
  (optional): the inventory rules; defaults are 25 units, 20%, 30 days, and 5 views.

Without `PORTKEY_API_KEY` the site still runs, but the chat assistant answers with a
"not configured" message and the inventory review falls back to plain-Python note writing.

**Terminal 2: front end**

```
cd frontend
npm install
npm run dev
```

Then open <http://localhost:5173>. The interactive API docs are at <http://localhost:8000/docs>.
(On the original machine the same two servers were also defined in a local `.claude/launch.json`, which is not committed.)

To change the assistant's voice or rules, edit `backend/prompts/prompt.md` (or
`inventory_prompt.md`) and save. The file is re-read on the next message; no restart needed.

## A five-minute demo

1. **Browse.** Open the home page, then Products. Click a product: large photo on the right, text
   on the left, size buttons showing real stock with sold-out sizes disabled.
2. **Ask for a category.** In the chat, ask "What hoodies do you have?" Cards appear in the reply
   and in the strip at the top; click one to open it.
3. **Ask about the page item.** On a product page ask "Do you have this in medium?" and
   "Is XL in stock?" The counts come from the database; a sold-out size is stated plainly.
4. **Spanish.** Ask "¿Tienen esto en talla XL?" (or pick Español in the widget). The reply is in
   Spanish with English product names and dollar prices.
5. **Sign in.** Log in as the test user (table below). The nav says "Hi, Test"; reload the page and
   the conversation is still there; ask "What's my email?".
6. **Cart.** Add a size to the cart, open Cart (totals, quantity capped at stock), then Checkout:
   the form pre-fills your name and "Place order" is greyed out by design.
7. **Owner.** Open the Inventory tab, read the low-stock and activity tables, click "Run inventory
   review", then "Mark resolved" on a note.
8. **Evidence.** Open `output/app_check.html` (61 checks, each with a screenshot) and run
   `python audit_trail.py --tail 3` in `backend` to show the agent loops you just caused.

## Running the full operational check

With both servers up:

```
cd backend
.venv\Scripts\python app_check.py
```

It exercises the API, accounts, the chatbot (every price and stock answer is compared with the
database), dynamic search, English and Spanish, customer memory, and the inventory notes, then
writes `output/app_check.html` and leaves the database as it found it. Browser-level results
recorded in `output/app_check_browser.json` are merged into the same report.

Each row of the report shows a screenshot of the check passing, taken from
`output/app_check_images/` through the mapping in `output/app_check_images.json` (relative paths,
so the `output` folder can be copied as a unit). To rebuild the HTML from the last saved results
without re-running the tests:

```
.venv\Scripts\python app_check.py --render-only
```

## Reading the audit trail

`output/audit_trail.json` gets one line per agent run: timestamp, agent, who asked (guest, shopper
email, or store owner), the request (message, page product, language), every tool call with its
arguments and a preview of the result, the proposed reply and whether the validator accepted it,
retries, token usage, duration, and the outcome. To read the last few runs:

```
cd backend
.venv\Scripts\python audit_trail.py --tail 5
```

The file is only ever appended to. It contains shopper messages and emails, so treat it like the
chat history table.

## Resetting the demo data

Using the site writes chat history, product events, and owner notes to the database. To return to
the seeded state (keeping all user accounts):

```
cd backend
.venv\Scripts\python reset_demo_data.py
```

Add `--keep-notes` to keep the owner's inventory notes. The audit trail is not touched.

## Test accounts

| Account | Email | Password | Notes |
|---|---|---|---|
| Test User (store owner) | test@campuscustoms.yale.edu | password | Seeded by the instructor; sees the Inventory tab |
| Handsome Dan | handsome.dan@example.com | BulldogBlue2026! | Created through the sign-up form during testing |

## Documentation map

- `output/harness.md`: the design record, step by step. Section 15 is the final outline of how
  the whole system works; section 14 covers the audit trail; section 13 the operational test.
- `output/app_check.html`: the operational test report with screenshots (61 of 61).
- `output/usability.md` and `output/design.md`: summaries of the usability upgrades and the
  visual redesign.
- `AI_prompts.md`: every prompt given to the AI assistant during the build, with what resulted.

## Before handing in

Build the archive with the script in this folder:

```
python make_submission.py
```

It writes `hw4.zip` next to the README (everything inside sits in a top-level `hw4` folder) and leaves out `backend/.env`
(the real gateway key and session secret; `backend/.env.example` is included instead),
`backend/.venv/`, `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`, and `data.zip` (the
original download; `data/` holds the same files). It then re-opens the archive and confirms that
no `.env` entry and no secret value is inside. The working folder is untouched, so the servers keep
running from it.
