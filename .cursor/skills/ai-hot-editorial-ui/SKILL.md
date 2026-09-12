---
name: ai-hot-editorial-ui
description: >-
  Builds dark editorial static sites (feed cards, sticky nav, data tables, bilingual shell)
  using the AI Hot Editorial design system. Use when the user wants AI Hot Digest style,
  editorial digest UI, dark feed layout, arena leaderboard tables, or edits
  design-system/tokens.css and editorial.css in this repo.
---

# AI Hot Editorial UI

Dark editorial digest sites — **not** marketing landings. Feed + tables + prose pages.

**Canonical CSS (this repo):** [`design-system/`](../../design-system/) — `tokens.css`, `editorial.css`, `index.css`.  
`src/site_build.py` concatenates these into `public/styles.css`; **edit CSS in `design-system/`, not inline in Python.**

## 0. Design Read (declare before coding)

State one line:

> Reading this as: **editorial digest** for **{audience}**, with a **dark glow-field** language, leaning toward **AI Hot Editorial** (VARIANCE 5 / MOTION 3 / DENSITY 2).

Do **not** apply `design-taste-frontend` landing defaults (centered hero, three feature cards, AI-purple mesh). This system is lower motion and data-forward.

## 1. CSS wiring

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{path}/tokens.css">
<link rel="stylesheet" href="{path}/editorial.css">
```

- Theme changes → edit **only** `design-system/tokens.css` `:root` variables.
- Never inline duplicate token values; use `var(--*)`.
- `theme-color` meta = `#0d0f17` (matches `--bg`).
- After CSS changes: `python -m src.site_build` then `pytest tests/test_site.py`.

## 2. Page shell (every page)

```html
<div class="site">
  <header class="site-header">
    <div class="brand-block">
      <p class="brand"><a href="…">Site Name</a></p>
      <p class="tagline">One-line description</p>
    </div>
  </header>
  <nav class="site-nav" aria-label="Primary">
    <div class="nav-primary"><!-- links --></div>
    <div class="lang-switch"><!-- lang toggle --></div>
  </nav>
  <!-- page content -->
  <footer class="site-footer">…</footer>
</div>
```

Home feed adds `<div class="read-progress" aria-hidden="true"></div>` before `.site`.

## 3. Page archetypes

| Archetype | Root classes | Notes |
|-----------|--------------|-------|
| Feed home | `.feed` + `.item` | Grid cards; optional `.feed-filter` tabs |
| Day groups | `.feed-day-sticky` | Full-width sticky date row inside `.feed` |
| Leaderboard | `.arena-page` + `.arena` + `.arena-table` | Rankings / Elo tables |
| Prose | `.prose` | About, Privacy, Disclosure |
| Archive | `.archive-list` | Date index |

Pick **one** main archetype per page. See [reference.md](reference.md) for HTML snippets.  
Live reference: `public/index.html`, `public/zh/arena.html`.

## 4. Feed item rules

```html
<article class="item" data-source="hn" data-heat="2" style="--i: 0">
  <span class="item-index" aria-hidden="true">01</span>
  <div class="item-body">…</div>
</article>
```

- `data-source` drives left accent color (`.item[data-source="…"]` in `editorial.css`).
- `data-heat` 1–3 scales headline weight.
- `--i` staggers `soft-in` animation delay.
- Badges: `.badge.badge-source`, `.badge.badge-tag`; meta: `.meta-text`.
- External links: `target="_blank" rel="noopener noreferrer"` when off-site.

## 5. Bilingual (en + zh-Hans)

- English at site root; Chinese under `/zh/` (mirror paths).
- `<html lang="en">` or `lang="zh-Hans"`.
- `<link rel="alternate" hreflang="…">` for en, zh-Hans, x-default.
- Nav: `.lang-switch` → `.lang-toggle` linking to the paired page.
- HTML structure is generated in `src/site_build.py`; keep class names aligned with `design-system/`.

## 6. Accessibility

- Sticky nav: keep `aria-label` on `<nav>`.
- Filter tabs: `role="tablist"` / `role="tab"` / `aria-selected`.
- Tables: `<th scope="col">`; wrap in `.arena-table-wrap` for horizontal scroll.
- Focus: rely on `:focus-visible` from editorial.css; don't remove outlines.
- Respect `prefers-reduced-motion` — don't add heavy animation on top.

## 7. Constraints

- **Vanilla CSS** — no Tailwind/Bootstrap unless user explicitly asks.
- **No new dependencies** for styling.
- **Do not** embed CSS in `site_build.py`; use `design-system/*.css`.
- **Do not** change public HTML generator signatures without user approval.

## 8. Pre-flight (before delivery)

- [ ] Changes in `design-system/*.css` (not Python string CSS)
- [ ] `python -m src.site_build` regenerates `public/styles.css`
- [ ] `pytest tests/test_site.py` passes
- [ ] `.site` shell + sticky `.site-nav` on all pages
- [ ] Bilingual pages have matching `hreflang` pairs
