# ShuttleScope — Design Direction v2 ("Precision on Gray")

> Single source of truth for the v2 redesign. Every implementer reads this first and
> conforms exactly. When in doubt: quieter, more precise, **lighter, less rounded**.
> Author: design lead (fable). Implementation: Sonnet.

## 0. Mood — one sentence
**A precise instrument, printed on gray.** Light, editorial, calm. A soft gray canvas
with clean white panels, ink typography, hairline rules, and tabular numerals — the feel
of a beautifully typeset scientific report, not a glowing "AI product." Structural rigor
(Linear/Stripe‑light, Height) with restraint. **Corners are crisp, not bubbly.** The
interface recedes so the data and the sport speak.

Three words to test every decision: **Quiet. Precise. Light.**

### Hard aesthetic rules from the client (do not violate)
- **Light, GRAY‑based is the default and the design target.** The soft gray canvas +
  white cards is the primary experience. NOT a dark/near‑black UI.
- **Dark mode is a secondary toggle only** — retuned to a calm warm **charcoal** (never
  pure black, never neon‑blue‑on‑black; that "AI aesthetic" is explicitly disliked). Do
  not design *for* dark; just make the toggle clean if used.
- **Corners are minimal / squared.** No needlessly rounded cards. Cards ≈6px, controls
  ≈5px. Full pills ONLY for true toggle/segmented/chip elements. Crisp > bubbly.

## 1. Non‑negotiable constraints (inherited)
- **Icons:** Material Symbols only, via `MIcon`. No emoji/lucide/ad‑hoc icon SVGs.
- **Copy:** all strings via i18n (`src/i18n/ja.json` + `en.json`); never hardcode JP/EN
  in TSX; `t()` only inside component/hook bodies (module‑scope `t()` crashes prod).
  Public Jinja uses its `_is_en` conditionals.
- **Light (gray) default; both themes refined.** Flip the app's default theme to light
  (see §10). Dark stays available but is not the driver.
- **Annotation hot path stays fast & keyboard‑first.** No transitions/animations on the
  annotate tiles, 9‑grid, or keyboard flows (`button[data-tile]`, mobile annotate).
- **Product safety:** never surface weakness/EPV/absolute win‑rate to players; always
  show confidence/uncertainty. Preserve `RoleGuard` / `ConfidenceBadge`.
- Respect `prefers-reduced-motion`. No external font/CDN assets (self‑host or system).

## 2. Color system — light gray primary
Depth on light comes from **white panels floating on a gray canvas + hairlines + very
subtle shadows** (real shadows read well on light). Define as CSS variables in
`globals.css` for BOTH themes; mirror the brand + surfaces into the public site.

### Light (DEFAULT — the star)
```
--ss-bg-app:        #F5F6F8   /* soft gray canvas — the paper */
--ss-surface-1:     #FFFFFF   /* cards / primary panels */
--ss-surface-2:     #EEF1F5   /* insets, table headers, secondary panels */
--ss-surface-3:     #E4E8EE   /* hover fills, active rows */
--ss-border:        #E3E7EC   /* hairline, default */
--ss-border-strong: #C9D1DB   /* inputs, emphasized dividers */

--ss-t1:            #1A2028   /* ink — primary text */
--ss-t2:            #55606E   /* secondary */
--ss-t3:            #8892A0   /* muted / captions */

--ss-brand:         #2563EB   /* THE single brand/interactive blue (unify everywhere) */
--ss-brand-hover:   #1D4FD7
--ss-brand-tint:    rgba(37,99,235,0.08)   /* subtle fills, selected states */
--ss-focus-ring:    rgba(37,99,235,0.32)   /* 3px focus ring */

--ss-good:          #1F6FE0   /* win/positive (blue family — matches data encoding) */
--ss-bad:           #C2334A   /* loss/negative */
--ss-warn:          #B26A00
--ss-success:       #197A48   /* verified/ok green (states only, not data) */
--ss-emphasis:      #E4610F   /* orange — MAX ONE per screen, the single hero stat */
```
### Dark (secondary toggle — calm charcoal, NOT black/neon)
```
--ss-bg-app:        #1C1F24   /* warm charcoal, not pure black */
--ss-surface-1:     #23272E
--ss-surface-2:     #2A2F37
--ss-surface-3:     #323842
--ss-border:        #363C46
--ss-border-strong: #454C58
--ss-t1:            #E6E9ED   /* soft, not #fff */
--ss-t2:            #A5AEBB
--ss-t3:            #727C89
--ss-brand:         #5C9BFF   /* lifted for contrast on charcoal */
--ss-brand-hover:   #7FB0FF
--ss-good:          #6AA6FF   --ss-bad: #F0808A   --ss-warn: #FCD34D
--ss-emphasis:      #F97316   --ss-success: #4BAE7A
```
Keep `src/styles/colors.ts` DATA scales (`A_GOOD`,`B_BAD`,`N_GRAY`, coolwarm, perfColor,
lightSafe, categoricalPalette) unchanged — do NOT recolor charts/heatmaps. The v2 tokens
govern **UI chrome** (surfaces/text/borders/interactive); the data blue and `--ss-brand`
must simply harmonize.

**Rule:** one saturated emphasis color visible per screen, max. Saturation is scarce —
spend it on the one number that matters. Everything else is gray, ink, and hairline.

## 3. Typography — precise numerals are the signature
- **Scale (rem):** display 2.25 · h1 1.75 · h2 1.375 · h3 1.125 · body 0.9375 · sm
  0.8125 · caption 0.75. Line‑height: headings 1.2, body 1.6.
- **Weights:** 600 headings, 500 UI labels/emphasis, 400 body. Avoid 700.
- **Tracking:** headings `-0.014em`; ALL‑CAPS micro‑labels `+0.06em` at 0.6875rem in
  `--ss-t3`; body normal.
- **NUMERALS (signature):** every metric/score/axis/timer uses
  `font-variant-numeric: tabular-nums slashed-zero;` — add a `.ss-num` utility and apply
  it to all figures/tables/axes. This one detail reads "instrument‑grade."
- **Fonts:** JP keeps MigMix 1P / Noto Sans JP. Latin+numerals: prefer a self‑hosted
  grotesk already in `src/assets/fonts/` (e.g. Inter) else `system-ui, -apple-system,
  "Segoe UI", Roboto, sans-serif`, always tabular. No external font CDN.

## 4. Space, radius (crisp), elevation
- **Spacing rhythm (4px):** 4·8·12·16·20·24·32·40·48·64·80. Sections breathe: desktop
  section padding ≥ 40px vertical; cards 16–20px. Whitespace *is* the refinement.
- **Radius — MINIMAL / squared (client preference):**
  `--r-sm 3px · --r-md 5px · --r-lg 6px · --r-xl 8px · --r-pill 999px`.
  Cards `--r-lg` (6px). Inputs/buttons `--r-md` (5px). Chips/badges `--r-sm`. `--r-pill`
  ONLY for real toggles/segmented controls/avatar. **Never** big bubbly radii.
- **Elevation (subtle, light‑tuned):**
  - `--e0` flat: hairline border only (default for panels on the gray canvas).
  - `--e1` `0 1px 2px rgba(16,24,40,.06)` — resting white cards.
  - `--e2` `0 1px 3px rgba(16,24,40,.10), 0 1px 2px rgba(16,24,40,.06)` — hover/raised.
  - `--e3` `0 10px 28px rgba(16,24,40,.14)` — modals/menus.
  Cards = white surface + hairline + `--e1`; hover → `--e2` (+ optional `translateY(-1px)`
  only where actionable). On the dark toggle, lean on surface steps + hairline (shadows
  weak on dark).

## 5. Motion — tokens + strict allow‑list
```
--dur-fast: 120ms · --dur-base: 180ms · --dur-slow: 300ms
--ease-out: cubic-bezier(0.2, 0, 0, 1)      /* crisp, decisive */
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)
```
**Allowed:** card hover lift (translateY(-1px)+`--e2`, `--dur-fast`); focus‑ring fade;
content mount fade+translateY(8px→0) `--dur-base` (list stagger ≤40ms, capped); skeleton
shimmer; tab active‑indicator slide; route crossfade `--dur-base`. **Forbidden:** motion
in the annotate hot path; parallax; springy/bouncy easing; anything delaying interaction.
All gated by `prefers-reduced-motion: reduce`.

## 6. Component recipes (conform)
- **Card:** `--ss-surface-1` (white), `1px solid --ss-border`, `--r-lg` (6px), `--e1`;
  hover (if actionable) `--e2` + `translateY(-1px)` `--dur-fast`. Header: title (500) +
  optional `MIcon` + right meta in `--ss-t3`. Crisp corners, not bubbly.
- **Metric/Stat:** tiny ALL‑CAPS label (`--ss-t3`) over a large `.ss-num` value; inline
  good/bad delta chip; `ConfidenceBadge` when statistical.
- **Button:** primary = `--ss-brand` / white text / `--r-md` / hover `--ss-brand-hover`;
  secondary = `--ss-surface-1` + `--ss-border-strong` hairline + ink text; ghost =
  transparent + hover `--ss-brand-tint`. Height 36px (44px touch). Focus ring always.
- **Input:** `--ss-surface-1`, `1px solid --ss-border-strong`, `--r-md`, 16px font on
  mobile. Focus: border→brand + 3px `--ss-focus-ring` (fade `--dur-fast`). Label above
  (500, `--ss-t2`); inline error in `--ss-bad` + `MIcon error` (no alert()).
- **Tab:** inactive `--ss-t2/t3`; active `--ss-t1` + 2px bottom indicator in `--ss-brand`
  (slides). Keep horizontal‑scroll + `scrollbar-hide` (never `flex-wrap`).
- **Badge/Chip:** `--r-sm` (or `--r-pill` only for true chips), tinted bg (semantic ~10%)
  + solid text. Never fully saturated status fills.
- **Sidebar nav:** icon + label; active = `--ss-brand-tint` bg + 2px `--ss-brand` left
  rail + `--ss-t1`; hover = `--ss-surface-2`. Collapsed = icon rail.
- **Empty state:** centered `MIcon` (36px, `--ss-t3`) + one calm line + one primary CTA.
  Honest; never fake data; keep "insufficient data / uncertainty" messaging.
- **Table:** hairline row rules, header row `--ss-surface-2`, hover row `--ss-surface-2/3`,
  numerals `.ss-num` right‑aligned. Below `md`, keep the existing card‑list fallback.

## 7. Public top page (highest‑impact)
Rework `backend/templates/public/*.j2` to **consume the same tokens** (create
`backend/public/design-tokens.css` from §2 so brand blue + surfaces match the app;
kill the `#1059c8` divergence).
- **Light, gray canvas** (`--ss-bg-app`) — NOT a dark/navy hero. Optional single very
  soft brand‑tint wash or fine hairline grid, restrained. Large tight headline (display),
  calm sub, one primary CTA + one ghost.
- **Product shot:** clean framed light screenshot, hairline border + `--e3`, gentle float
  (no perspective). Show the real light UI.
- **Feature icons:** Material Symbols (match the app), not hand‑drawn SVGs.
- Sections: ≥80px rhythm, hairline dividers, §6 cards, tasteful once‑only scroll‑reveal
  (reduced‑motion aware). Unified nav/footer + wordmark. Bilingual, theme toggle, single
  self‑contained page. Default appearance = light.

## 8. Per‑surface briefs (workstreams; disjoint file ownership)
1. **Foundation (first, owns tokens):** `globals.css` (both themes per §2/§4/§5, LIGHT as
   default — see §10; `.ss-num`; radius/elevation/motion vars; reduced‑motion), 
   `tailwind.config.js` (radius/shadow/duration/ease → vars), `src/styles/colors.ts`
   (bridge brand only; keep data scales), NEW `backend/public/design-tokens.css`. Add,
   don't rip out; alias any still‑referenced legacy var.
2. **Public site:** `backend/templates/public/*.j2` per §7.
3. **Auth & onboarding:** `LoginPage`, `RegisterPage`, `OnboardingConsentPage`,
   password/verify/invite — refined forms, calm branded panel/card, clear MFA step.
4. **App shell:** `App.tsx` Sidebar + `DashboardTopNav` — §6 nav/tab recipes, active
   indicators, subtle elevation, icon polish.
5. **Cards & common:** `src/components/common/*` (`ConfidenceBadge`, `useCardTheme`, card
   wrappers), match list card/row — §6 cards, `.ss-num`, hover.
6. **Dashboards & charts:** `src/pages/dashboard/*`, research/analysis cards, Recharts
   theming (brand palette, tabular axes, custom light tooltip, faint gridlines), empty
   states.

## 9. Definition of done (per surface)
- Conforms to §2–§6 (no new hardcoded hex outside the token layer; crisp radii).
- LIGHT is default and beautiful; dark toggle clean; mobile (≤`md`) intact;
  `prefers-reduced-motion` honored.
- Material Symbols only; new copy in i18n; `t()` inside components.
- `npm run check:i18n` clean; `npm run build` passes; annotate hot path untouched.
- Screenshot‑reviewed on desktop + mobile (light) before merge.

## 10. Flip default theme to LIGHT
The app currently defaults to dark. Find the theme init (theme hook `src/hooks/use*Theme*`,
a `<ThemeProvider>`, and/or the inline `data-theme` bootstrap in `index.html`/electron
preload/App). When **no stored preference exists**, default `data-theme="light"`. Preserve
the user toggle + localStorage persistence (respect an explicit stored 'dark'). Verify the
initial paint is light (no dark flash). This is part of the Foundation stream.
