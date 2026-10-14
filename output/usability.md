# Campus Customs: usability upgrades

Summary of the usability work done on 2026-10-13, after the core site, accounts, and shopping
assistant were complete. Full detail, with verification logs, is in `harness.md` (sections 8–11).

## Front end

### 1. Website styling based on the yale.edu theme

The original site used a generic blue-and-gray "web app" look. It was re-skinned to follow
yale.edu's visual system, read directly from that site's computed styles, while keeping product
cards as the way information is presented.

- **Typography:** EB Garamond (a Renaissance-style serif, the closest open font to Yale's own
  face) for the wordmark, nav items, headlines, and prose; Source Sans 3 (a humanist sans) for
  small uppercase labels, buttons, prices, and the footer strip, at 12–14px with letter-spacing.
- **Color and shape:** Yale Blue #00356B, link blue #286DC0, #222 text, #DDD 1px rules, white
  backgrounds with light gray frames, square corners on buttons, inputs, and cards.
- **Header:** a thin blue stripe, an uppercase utility row, a large centered serif wordmark, and a
  serif navigation row between thin rules that stays pinned as the page scrolls.
- **Home:** a text-forward hero with eyebrow label, serif headline, and a framed collage of real
  product photos; collection tiles with product photos and "EXPLORE →" links; fan favorites; a
  callout whose button opens the assistant.
- **Everywhere else:** eyebrow labels and serif titles on Products, item pages, About, forms, cart,
  checkout, and the owner page; a serif-and-blue footer; a square chat panel with a serif header.
- Design tokens live at the top of `frontend/src/index.css`, so the look is defined in one place.

This look was approved as the baseline for the rest of the assignment (see `design.md`).

### 2. Ability to place an order (demo checkout)

Shoppers can now go from browsing to a completed order form, with ordering itself intentionally
switched off because this is a sample store with no payment system.

- **Item page:** a size picker that shows the exact stock per size ("15 in stock", "5 left",
  "Out of stock"), disables sold-out sizes, pre-selects the first available size, caps the
  quantity at what is in stock, and an "Add to cart" button that confirms with a link to the cart.
- **Cart tab:** in the main nav, with a blue badge showing the item count; hidden when empty.
- **Cart page:** thumbnail, name, size, unit price, editable quantity (still capped at stock),
  remove, line totals, and a summary with subtotal and total. The cart persists across reloads.
- **Checkout page:** a banner explaining ordering is off; contact details pre-filled from the
  account; shipping address; a payment section labelled as not connected (nothing typed there is
  stored); a greyed-out "Place order" button with an explanation; an order summary.
- Nothing was added to the back end for this: the cart lives in the browser and there is no
  orders table or payment code, which keeps the demo boundary unambiguous. The assistant knows how
  ordering works and that it cannot place orders itself.

## Back end

### 3. English and Spanish ability for the chatbot

The website stays in English; the assistant understands and answers in English or Spanish.

- **Auto by default:** the agent replies in the language of the shopper's latest message and
  switches when they switch. A selector in the chat header (Auto / English / Español) can force a
  language; the panel's own strings follow it and the choice is remembered.
- **Honest in both languages:** product names stay as the catalogue has them, prices stay as US
  dollars, sizes stay XS–XXL, and Spanish stock wording is explicit ("agotado", "quedan 5").
  Colors and garment types are translated.
- **Spanish search:** the prompt tells the model to translate keywords before searching, and the
  search tool strips accents, ignores Spanish filler words, and maps common Spanish words for
  garments, colors, family members, sports, and schools to the English catalogue, so "algo para
  mi abuela" finds the Yale Grandma Hoodie and "béisbol" finds the baseball items.
- Verified with 16 scripted checks and a browser run in Spanish.

### 4. Views and inventory tracking for management

The site records what shoppers look at and add to carts, applies two plain rules, and has a
second agent send the owner notes.

- **Tracking:** product card clicks, item page views, and add-to-carts (with size and quantity)
  are recorded in a new `product_events` table. Checkout is a demo, so add-to-cart is the order
  signal.
- **Rules (plain Python, no model needed):** a size at or below 20% of a 25-unit par (5 or fewer)
  flags its product for a reorder note; a product with 5 or more views and clicks in 30 days and
  no add-to-carts is flagged "viewed but not ordered".
- **The inventory assistant:** a PydanticAI agent reads the report and sends notes through a tool
  that refuses unflagged products and duplicates. One review handles the 10 most urgent products
  of each kind and reports the backlog. Notes land in an `owner_notes` table and in
  `output/owner_inbox.md`.
- **Owner page:** an Inventory tab appears for the owner's account (`OWNER_EMAIL`, default the
  seeded test user) with a "Run inventory review" button, the open notes with Mark resolved, and
  the numbers behind them: low-stock sizes and shopper activity with flags.
- Verified: 16 scripted checks (rules, agent review, no duplicates, backlog, resolve, inbox file),
  API access checks (guests 401, other accounts 403, owner 200), and a browser run of the owner
  page.
