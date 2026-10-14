# Campus Customs: visual design

The website's look, adopted on 2026-10-13 and approved as the baseline for the rest of the
assignment. It follows yale.edu's visual system while keeping product cards as the way
information is presented. Section 8 of `harness.md` has the page-by-page detail and verification.

## Where it came from

yale.edu was opened in the browser and its computed styles were read rather than guessed:

| Element | yale.edu | Campus Customs |
|---|---|---|
| Headlines, nav items, body copy | `yale`, Yale's own Baskerville-class serif, 20–33px, weight 400 | **EB Garamond** (Google Fonts), the closest open serif, same sizes and weight |
| Labels, buttons, utility links | `Mallory-Medium`, humanist sans, 14px uppercase, 0.55–0.75px tracking | **Source Sans 3** (Google Fonts), 12–14px uppercase, 0.08–0.1em tracking, weight 600 |
| Primary color | Yale Blue `#00356B` | same |
| Link / accent | `#286DC0` | same, for eyebrow labels and text links |
| Text | `#222` | same |
| Rules and borders | `#DDD`, 1px | same |
| Backgrounds | white page, light bands | white page, `#F5F5F5` frames and bands |
| Buttons | rectangular, Yale Blue, white uppercase sans | same |
| Header | large centered serif wordmark over a serif nav row, small uppercase utility links above | same, plus a 6px blue top stripe and a sticky nav row |
| Hero | framed image, eyebrow label, serif headline, uppercase text links | same pattern with a framed collage of product photos |
| Tiles | image, small uppercase category label, serif title, uppercase "EXPLORE" link | same, with the image in a light gray frame |

## The tokens

Defined once at the top of `frontend/src/index.css`:

```
--blue #00356B   --blue-dark #002A55   --blue-link #286DC0
--ink #222       --muted #5A5A5A       --rule #DDD      --light #F5F5F5
--serif 'EB Garamond', ...   --sans 'Source Sans 3', ...   --max 1200px
```

Shared classes: `.eyebrow` (small uppercase sans label in link blue), `.btn` / `.btn-outline`
(square buttons), `.text-link` (uppercase link that appends an arrow), `.section` (48px rhythm
with a 1px rule between sections), `.section-head` (eyebrow and serif title left, text link
right). Every component uses these, so a palette or typeface change is one edit.

## Page by page

- **Header:** blue stripe, then an uppercase utility row (store tagline; "Signed in as…"), then
  a centered 54px serif wordmark with a tracked tagline, then a serif nav row between rules,
  pinned on scroll, with the active page underlined in blue. A Cart tab with a count badge; an
  Inventory tab for the owner.
- **Home:** two-column hero (text left; staggered four-photo collage right, each photo in a gray
  frame with a serif caption); "Shop by spirit" tiles using real product photos; "Fan favorites"
  cards; a light gray callout whose "Start a chat" button opens the assistant.
- **Products:** eyebrow "The catalogue", 44px serif title, serif subtitle, the card grid.
- **Product card:** gray image frame, uppercase garment-type eyebrow, 22px serif name, bold blue
  price, muted one-line description; square corners, 1px rule border, soft blue shadow on hover.
  The same component serves the grid, the "Picked for you" strip, and the home page.
- **Item page:** eyebrow garment type, 44px serif title, bold price, 20px serif description, then
  uppercase ruled section labels for Colors, Choose a size (the stock-aware size picker), and Add
  to cart; the photo in a large gray frame on the right.
- **Cart and checkout:** serif item names, square inputs, light gray summary panel, square blue
  buttons, a left-bordered demo banner, and a greyed-out "Place order".
- **About:** serif prose at 20px with ruled section headings.
- **Forms:** bordered card, serif heading and lead, uppercase field labels, square inputs with a
  blue focus ring, left-bordered note and error boxes.
- **Owner page:** notes as left-bordered cards (amber for reorder, blue for do-not-reorder), and
  uppercase-labelled report tables.
- **Footer:** top rule, serif wordmark and tagline, uppercase-labelled link columns, Yale Blue
  bottom strip.
- **Chat panel:** square, blue header with serif title, a language selector, gray assistant
  bubbles with a rule border, blue user bubbles, square mini product cards, uppercase Send button.

## Rules for new work

Use the tokens and shared classes above; keep product cards for product information; square
corners; no gray page backgrounds; serif for headings, nav, and prose; uppercase sans for labels
and buttons.
