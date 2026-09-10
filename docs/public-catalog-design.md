# Public Catalog design

## 1. Visual theme and atmosphere

The public Catalog is a dark technical ledger: compact, evidence-led, and deliberately quieter than a product landing page. It privileges current facts over claims.

## 2. Color palette and roles

| Token | Value | Role |
| --- | --- | --- |
| Canvas | `oklch(0.17 0.014 62)` | Page ground |
| Surface | `oklch(0.215 0.016 62)` | Table surface |
| Text | `oklch(0.91 0.018 82)` | Primary reading text |
| Muted | `oklch(0.71 0.022 76)` | Supporting metadata |
| Accent | `oklch(0.78 0.13 76)` | Count, links, and state |

## 3. Typography

Headlines and project names use the locally available Palatino family for an editorial record feel. System sans-serif handles prose; system monospace handles timestamps and numeric facts with tabular figures. No remote font or tracking asset is loaded.

## 4. Components

The page has a compact masthead, one scrollable data table, status pills, and a plain footer. Links have visible keyboard focus; the table gains a subtle background step on pointer hover.

## 5. Layout

The page is a single centered ledger with a 1120px maximum width. On narrow screens the table scrolls horizontally instead of hiding data or changing column meaning.

## 6. Depth and elevation

Near-black canvas and low-opacity warm surfaces establish hierarchy. The table uses a single hairline outline and row separators, not card grids or decorative shadows.

## 7. Guardrails

- Render only name, repository URL, category, stage, tracking, Stars, and observation time.
- Never embed project YAML, research, context, personal notes, discovery URLs, or run logs.
- Do not add remote scripts, fonts, analytics, cookies, or images.
- Do not deploy output built from pull requests or non-`main` refs.
- This repository and its Pages site are public. The artifact is not an access-control boundary: private authoritative knowledge must live in a separate private repository or other private system, and must never be supplied to `render-site`.
- The renderer accepts only the checked-in, public-safe project and observation records, emits exactly `index.html` and `404.html`, and rejects a destination containing any other file.

## 8. Responsive behavior

The page remains readable from 320px wide. Touch devices do not retain hover styling, and reduced-motion preferences suppress transitions.

## 9. Prompt guide

Keep future public Catalog elements on `Canvas`, use Palatino for display text and monospace for facts, reserve `Accent` for verified data/link emphasis, preserve the `4px / 10px / pill` radius scale, and never expose fields outside the explicit allowlist.
