# ai_hot

个人向 **AI 垂直热点定时巡检**：HN + Reddit + Google News + 官方/镜像 RSS → SQLite 去重 → `out/digest.md`（**UTC 当日累计**）→ 归档 `content/digests/` → 静态站 **AI Hot Digest**。

网站：[https://ai-hot.tonysingwm.workers.dev/](https://ai-hot.tonysingwm.workers.dev/)

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

质量闭环：`pytest` · `mypy src` · `ruff check src`

## Admin Portal（本地编辑）

浏览器管理热搜与 Digest，避免手改 JSON/Markdown。

```bash
pip install -e ".[admin,dev]"
python -m src.admin
# → http://127.0.0.1:8787/
```

| 功能 | 说明 |
|------|------|
| 今日热搜 | CRUD `content/hot_topics/latest.json` |
| Digest 归档 | 按日编辑 `content/digests/YYYY-MM-DD.{en,zh}.md` |
| 翻译全部标题 | 批量补 `title_zh`（跳过已有） |
| **ADHD 摘要** | 只生成中文 ADHD（约 30 次 LLM/轮） |
| **ADHD Summary** | 只生成英文 ADHD（约 30 次 LLM/轮） |
| 行内 摘要 / EN | 单条按语种生成 |
| **停止** | 遮罩层红色按钮；每条成功后立即落盘，已完成的保留 |
| 重建站点 | 只读本地 `content/` 构建 `public/`（不重新 probe） |
| 发布推送 | `git add content/*` → commit → push |

**建议流程：** 编辑/生成 ADHD → **重建站点** 预览 → **发布推送** 上线。

> 翻译与 ADHD 任务互斥（同时只跑一个）。中断后再点同语种按钮，只处理缺失条目。

## CLI 流水线

### Digest：生成 → 归档 → 伴读 → push

```bash
python -m src.main --llm qwen && python -m src.publish && python -m src.speak \
  && DAY=$(date -u +%Y-%m-%d) \
  && git add content/digests content/audio \
  && git commit -m "content: archive digest $DAY" && git push
```

### Digest：单条/批量 ADHD 精写

```bash
# 单条
URL='https://example.com/article'
python -m src.deep_summarize --url "$URL" \
  && python -m src.publish && python -m src.speak --url "$URL" \
  && git add content/digests content/audio && git commit -m "content: adhd summarize" && git push

# 批量（重复 --url；speak 会重生成这些条的中英 mp3）
URLS=(
  'https://example.com/a'
  'https://example.com/b'
)
ARGS=(); for u in "${URLS[@]}"; do ARGS+=(--url "$u"); done
python -m src.deep_summarize "${ARGS[@]}" \
  && python -m src.publish && python -m src.speak "${ARGS[@]}" \
  && git add content/digests content/audio && git commit -m "content: adhd summarize" && git push
```

### 今日热搜（CLI）

```bash
python -m src.hot_topics_probe --top 30 --save          # 拉榜
python -m src.deep_summarize --hot-topics --llm qwen    # ADHD 中+英（CLI 无分语种）
python -m src.site_build                                # 本地预览
```

快照：`content/hot_topics/latest.json`。`config.yaml` → `hot_topics.deep_summarize: true` 时 `site_build` 可自动精写（`deep_summarize_top_n: 0` = 全部）。

### 其他常用

```bash
python -m src.main --llm openrouter          # 云端 LLM（需 OPENROUTER_API_KEY）
python -m src.translate                      # 增量译中文
python -m src.resummarize --llm qwen         # 重写 junk 摘要
pip install -e ".[speak]" && python -m src.speak   # TTS 伴读
```

## 发布

`out/` 不进 git。归档 → 本地构建 → push（Actions 部署 Cloudflare）。

```bash
python -m src.publish              # → content/digests/YYYY-MM-DD.{en,zh}.md
python -m src.site_build           # → public/
git add content/digests && git commit -m "content: archive digest YYYY-MM-DD" && git push
```

**Cloudflare（当前）：** Workers + `wrangler.toml`。Build：`pip install -e . && python -m src.site_build`；Deploy：`npx wrangler deploy`。详见仓库内 wrangler / Actions 配置。

定时：GitHub Actions `digest-schedule.yml`，港时 **07:00 / 12:00 / 21:00**（需 Secret `OPENROUTER_API_KEY`）。

## 配置

- 业务阈值 / RSS / 站点：`config.yaml`
- 密钥：`.env`（勿提交）；Actions 用 `OPENROUTER_API_KEY`
- Threads 热搜：`.env` 的 `THREADS_ACCESS_TOKEN` + `config.yaml` `threads.enabled: true`

## 扫描源

均在 `config.yaml`：HN · Reddit · Google News RSS · OpenAI / Google AI / DeepMind / Anthropic（镜像）/ Hugging Face / NVIDIA / Apple / 量子位 等。

**未扫（后置）：** X/Twitter、国内热搜、推送渠道。

## 非目标（v1）

推送、数字人视频、自动发帖、AdSense。口播 + TTS 可用（`python -m src.speak`）。
