# Aurora Console design system

## Principles

- **Calm confidence.** Deep space surfaces, a restrained aurora accent, clear
  hierarchy. Accent is at most 5% of the visible surface.
- **One hero per page.** The most important state gets the largest treatment;
  everything else is supporting evidence.
- **Progressive disclosure.** Common actions first; MTU, stack, raw JSON and
  diffs live behind “Advanced”.
- **Accessible by construction.** Keyboard, focus, contrast, reduced motion and
  screen reader labels are part of the component contract.
- **Performance is design.** Blur is limited to chrome and hero surfaces; charts
  load lazily; tables never animate layout.

## Tokens

CSS variables live in `web/src/styles/tokens.css`; Naive UI overrides in
`web/src/design/theme.ts`. Never hard-code colors in pages.

| Token | Dark | Light |
|---|---|---|
| `--bg` | `#060911` | `#F4F7FC` |
| `--surface` | `rgba(13,21,36,.78)` | `#FFFFFF` |
| `--surface-2` | `#101A2B` | `#EDF2FA` |
| `--text` | `#EDF3FF` | `#0F172A` |
| `--text-2` | `#A7B6CE` | `#475569` |
| `--accent` | `#5EEAD4` | `#0F766E` |
| `--accent-2` | `#60A5FA` | `#2563EB` |
| `--success` | `#34D399` | `#047857` |
| `--warning` | `#FBBF24` | `#B45309` |
| `--danger` | `#FB7185` | `#BE123C` |

Spacing is a 4px base (8/12/16/20/24/32/40/48). Radii: 8/12/16/24.
Shadows are for elevation only; borders carry structure.

## Typography

Inter Variable is self-hosted. Chinese falls back to PingFang SC, Microsoft
YaHei or Noto Sans CJK SC. Display 30/38, H1 24/32, H2 18/26, body 14/22,
small 12/18, micro 11/16. Numbers use `font-variant-numeric: tabular-nums`.
Logs use the monospace stack.

## Components

`OPageHeader`, `OSectionCard`, `OStatCard`, `OStatusPill`, `OCopyButton`,
`OQrModal`, `OEmptyState`, `OErrorState`, `OSkeletonPage`, `OConnectOrb`,
`OTrafficChart`, `OLazyChart`, `OCommandPalette`, `OJobDrawer`,
`OShortcutModal`, `OBrandMark`.

Rules:

- One `h1` per page (the page header).
- Cards do not nest cards; use dividers and sub-sections.
- Status is icon + text, never color alone.
- Every page defines empty, loading, error and permission-denied states.
- Destructive actions require a dialog that explains the consequence.

## Charts

ECharts with a custom palette. 2px lines, 12% area fill, dashed horizontal grid,
no vertical grid, tooltips in a glass surface, 300ms animation. Time series are
lines/areas; rings are reserved for quota/health.

## Motion

150–220ms, `cubic-bezier(.2,.8,.2,1)`. Page enter is fade + 8px rise. No
continuous spinning or flashing. `prefers-reduced-motion` disables all of it.
Connection state uses a slow breathing glow, not an alarm.

## Layout

Sidebar 248px (collapsible 76px), topbar 64px, content max 1600px. Breakpoints:
≥1440, 1024–1439, 768–1023, <768, <480. On phones the sidebar becomes a drawer
and the bottom nav keeps four primary destinations.

## Verification

Playwright visual baselines at 1440/1024/390 in dark and light; axe checks for
serious/critical issues; first-screen JS < 300 KB gzip; LCP < 2.5s; INP < 200ms;
CLS < 0.05. See `docs/ux.md` for the usability script.
