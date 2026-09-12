# AI Hot Editorial — Reference

CSS source of truth: [`design-system/`](../../design-system/).

## Token map

| Variable | Default | Use |
|----------|---------|-----|
| `--bg` | `#0d0f17` | Page background |
| `--bg-elev` | `rgba(255,255,255,0.05)` | Cards, panels |
| `--ink` / `--muted` | `#e2e8f0` / `#94a3b8` | Body / secondary text |
| `--accent` / `--accent-hot` | `#a5b4fc` / `#c4b5fd` | Links, ranks, emphasis |
| `--line` | `rgba(255,255,255,0.12)` | Borders |
| `--radius` | `16px` | Cards, panels |
| `--pad` | `clamp(1.5rem, 5vw, 2.5rem)` | Page padding |
| `--max` | `72rem` | Content max-width |

## Feed home

```html
<div class="read-progress" aria-hidden="true"></div>
<div class="site">
  <!-- header + nav -->
  <nav class="feed-filter" role="tablist" aria-label="Filter">
    <button type="button" class="feed-filter-tab is-active" role="tab"
      aria-selected="true" data-filter-kind="" data-filter="">All</button>
    <button type="button" class="feed-filter-tab" role="tab"
      aria-selected="false" data-filter-kind="tag" data-filter="paper">Paper</button>
  </nav>
  <main class="feed" id="feed">
    <div class="feed-day-sticky" data-day="2026-09-12">
      <time datetime="2026-09-12">2026-09-12</time>
    </div>
    <article class="item" data-source="rss:openai" data-heat="2" style="--i: 0">
      <span class="item-index" aria-hidden="true">01</span>
      <div class="item-body">
        <div class="item-meta">
          <span class="badge badge-primary badge-source">rss:openai</span>
          <span class="meta-text">2026-09-12</span>
        </div>
        <h2>Headline</h2>
        <p class="summary">Summary paragraph.</p>
        <p class="why"><span class="label">Why</span> One-line rationale.</p>
        <div class="item-actions">
          <a class="item-read" href="https://example.com" target="_blank"
            rel="noopener noreferrer">Read</a>
        </div>
      </div>
    </article>
  </main>
</div>
```

## Arena / leaderboard

```html
<h1 class="page-title">Leaderboard</h1>
<p class="meta arena-page-intro">Intro copy. Data refreshes on build.</p>
<main class="feed arena-page">
  <section class="arena" aria-labelledby="arena-text">
    <div class="arena-head">
      <h2 id="arena-text">Text (as of 2026-09-12)</h2>
    </div>
    <div class="arena-table-wrap">
      <table class="arena-table">
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Model</th>
            <th scope="col">Org</th>
            <th scope="col">Score</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="arena-rank">1</td>
            <td>Model Name</td>
            <td>Vendor</td>
            <td class="arena-elo">1421</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="arena-note">
      Source: <a href="https://arena.ai" target="_blank" rel="noopener noreferrer">Arena AI</a>
      · Third-party data.
    </p>
  </section>
</main>
```

## Prose page (About / Privacy)

```html
<h1 class="page-title">About</h1>
<main class="prose">
  <p>Paragraph…</p>
</main>
```

## Archive index

```html
<h1 class="page-title">Archive</h1>
<ul class="archive-list">
  <li><a href="archive/2026-09-12/">2026-09-12</a></li>
</ul>
```

## Head meta checklist

```html
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0d0f17">
<link rel="canonical" href="…">
<link rel="alternate" hreflang="en" href="…">
<link rel="alternate" hreflang="zh-Hans" href="…">
<link rel="alternate" hreflang="x-default" href="…">
```

## Source colors (`data-source`)

Built-in accent overrides in `design-system/editorial.css`:

| `data-source` | Accent |
|---------------|--------|
| `hn` | `#c45c26` |
| `openai`, `rss:openai`, `rss:openai_youtube` | `#1a7f64` |
| `google_ai`, `rss:google_ai` | `#3b6ea5` |
| `deepmind`, `rss:deepmind` | `#2a8f8a` |
| `anthropic`, `rss:anthropic` | `#b56a4a` |
| `huggingface`, `rss:huggingface` | `#b0891d` |
| `nvidia_ai`, `rss:nvidia_ai` | `#4a9a3e` |
| `apple_*`, `rss:apple_*` | `#6b7280` |
| `qbitai`, `rss:qbitai` | `#6b5b8a` |

Add new sources in `design-system/editorial.css`:

```css
.item[data-source="rss:new_source"] { --source: #hex; }
```

## Copying to another project

1. Copy `design-system/` directory.
2. Adjust `tokens.css` for brand if needed.
3. Use archetype HTML from this file.
4. Keep class names stable — CSS selectors depend on them.
