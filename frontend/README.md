# Watchtower web

The Watchtower website and app: Next.js 16 (App Router, Cache Components), React 19, Tailwind CSS 4, Motion,
TanStack Query and Radix primitives. It talks to the FastAPI backend in `../backend`.

```bash
npm install
cp .env.example .env.local      # WT_BACKEND_URL points at the API (default http://127.0.0.1:8000)
npm run dev                      # http://localhost:3000
npm run build && npm start       # production
npm run lint
```

## How it fits together

- **Same-origin gateway** (`src/app/v1/[...path]/route.ts`). The browser only ever calls `/v1/*` on this origin.
  The gateway attaches the session from httpOnly cookies, refreshes expiring tokens, moves tokens returned by
  sign-in endpoints into cookies (page scripts never see them), blocks cross-site mutations (custom
  `x-wt-csrf` header plus Origin check) and streams Server-Sent Events through, closing the API connection
  as soon as the browser goes away. Pro API tokens (`Authorization: Bearer wt_…`) pass straight through.
- **Auth**: email/password, magic link and one-time code, password reset, and Google via Supabase's redirect;
  `/auth/callback` adopts sessions that arrive in the URL fragment through `/api/session`. `src/proxy.ts`
  only does optimistic redirects. The API checks every request.
- **Public pages** (`/`, `/explore`, `/explore/[slug]`, `/pricing`, `/docs`, legal) are server-rendered from
  cached API reads (`src/lib/server/public-api.ts`) with metadata, JSON-LD, `sitemap.xml` and `robots.txt`.
- **The app** (`/dashboard`, `/watches/new`, `/watches/[id]`, `/alerts`, `/community`, `/settings`, `/admin`)
  is client-rendered with TanStack Query. One SSE connection per tab (`src/lib/stream.tsx`) carries the user's
  events plus any watch on screen, replays recent watch history for the live log, and reconnects with backoff.
- **Push**: `public/sw.js` shows Web Push alerts; `src/lib/push.ts` subscribes with the API's VAPID key.

## Design system

| | Light | Dark |
|---|---|---|
| Background / surface | parchment `#f0ece2` / `#f6f3eb` | `#0f1210` / `#161a17` |
| Ink | forest-black `#14201b` | warm cream `#ede7da` |
| Primary action | deep forest `#1b3a2f` | amber `#e8a54a` |
| Accent | amber `#e29a3b` (fills), `#9a5810` (text, AA) | `#f0b462` |

All colours are CSS variables in `src/app/globals.css` (`--ink`, `--line`, `--amber-ink`, …) exposed to
Tailwind as `text-ink`, `bg-elevated`, `border-line` and so on. Text tokens meet WCAG AA on both backgrounds;
the bright amber is used only for fills and large display type.

Typography: **Newsreader** (optical-size display serif, italic accents) for headlines, **Schibsted Grotesk**
for interface text, **Martian Mono** (narrowed with its width axis) for the instrument-panel labels such as
`[01] HOW IT WORKS`. All three are self-hosted through `next/font`.

Illustrations (radar, observatory scene, contour maps, category art) are generated SVG in
`src/components/art`, so they stay sharp, theme with the palette and cost no image requests. Motion respects
`prefers-reduced-motion` globally (`MotionConfig reducedMotion="user"` plus a CSS override).
