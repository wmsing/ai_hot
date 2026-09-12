# AI Hot Editorial

暗色编辑型静态站 UI：feed 卡片、粘性导航、数据表、双语壳层。源自 [AI Hot Digest](https://ai-hot.tonysingwm.workers.dev/)。

**设计拨盘：** VARIANCE 5 / MOTION 3 / DENSITY 2（暗色光场 + 低动效 + 疏朗排版）

## 快速接入

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="path/to/design-system/tokens.css">
<link rel="stylesheet" href="path/to/design-system/editorial.css">
```

或单文件入口（构建工具需处理 `@import`）：

```html
<link rel="stylesheet" href="path/to/design-system/index.css">
```

## 自定义主题

只改 `tokens.css` 里的 `:root` 变量即可换色/间距，不必动组件类：

| 变量 | 用途 |
|------|------|
| `--bg` / `--bg-elev` | 页面底与卡片底 |
| `--ink` / `--muted` | 正文与次要文字 |
| `--accent` / `--accent-hot` | 链接与强调 |
| `--line` / `--radius` / `--shadow` | 边框、圆角、阴影 |
| `--pad` / `--max` | 页边距与内容最大宽度 |

## 页面骨架

```html
<div class="site">
  <header class="site-header">
    <div class="brand-block">
      <p class="brand"><a href="/">Site Name</a></p>
      <p class="tagline">One-line description</p>
    </div>
  </header>
  <nav class="site-nav" aria-label="Primary">
    <div class="nav-primary">
      <a href="/">Home</a>
    </div>
    <div class="lang-switch">
      <a href="/zh/" class="lang-toggle" hreflang="zh-Hans">中文</a>
    </div>
  </nav>
  <main class="feed" id="feed">
    <article class="item" data-source="hn" style="--i: 0">
      <span class="item-index" aria-hidden="true">01</span>
      <div class="item-body">
        <div class="item-meta">
          <span class="badge badge-source">source</span>
          <span class="meta-text">2026-09-12</span>
        </div>
        <h2>Headline</h2>
        <p class="summary">Summary text.</p>
      </div>
    </article>
  </main>
  <footer class="site-footer">Footer</footer>
</div>
```

## 组件索引

| 类名 | 场景 |
|------|------|
| `.feed` / `.item` | 信息流卡片网格 |
| `.feed-day-sticky` | 按日分组粘性标题 |
| `.feed-filter` / `.feed-filter-tab` | 标签筛选 |
| `.arena` / `.arena-table` | 排行榜/数据表 |
| `.archive-list` | 归档列表 |
| `.prose` | 长文页（About / Privacy） |
| `.read-progress` | 顶部阅读进度条 |

## Agent Skill

仓库内 Cursor Skill：`.cursor/skills/ai-hot-editorial-ui/`（协作者 clone 即用）。

## 许可

与主仓库相同。复制 `design-system/` 目录即可复用。
