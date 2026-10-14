# Campus Customs front end

React 19 + Vite + TypeScript. The project-level guide (how everything fits together, running both
servers, the demo script, tests) is in the root `README.md`; the design record is in
`output/harness.md`.

Front-end specifics:

- `npm install` once, then `npm run dev` serves <http://localhost:5173>.
- `vite.config.ts` proxies `/api` and `/media` to the FastAPI back end on port 8000 and uses
  polling file watching (`server.watch.usePolling`) so edits are picked up inside a OneDrive folder.
- Routes live in `src/App.tsx`; pages in `src/pages/`; shared pieces in `src/components/`
  (`NavBar`, `ProductCard`, `RecommendedStrip`, `ChatWidget`).
- State: `AuthContext` (signed-in user from `/api/auth/me`), `CartContext` (browser-only cart in
  `localStorage`), `PicksContext` (products the chat put on the page).
- Styling is one file, `src/index.css`, built on yale.edu-style tokens (EB Garamond, Source Sans 3,
  Yale Blue, square corners).
