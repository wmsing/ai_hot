# ai_hot

个人向 **AI 垂直热点定时巡检**：HN + 官方/镜像 RSS → SQLite 去重 → `out/digest.md`。  
静态站 **AI Hot Digest**（中文副标题「AI 热点摘要」）经 Cloudflare Pages 发布。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# 手动跑一次（v1 验收，模式 A：RSS 原生简介）
python -m src.main
# 模式 B：入选条目用本地 Ollama（qwen）生成简介
python -m src.main --llm qwen
# 查看：out/digest.md ，库：data/ai_hot.db

# 本地 Ollama（默认 qwen3:4b-instruct）译成中文
python -m src.translate
# 查看：out/digest.zh.md
```

落地到 24h 机器后用 cron（每小时）：

```bash
0 * * * * cd /path/to/ai_hot && .venv/bin/python -m src.main >> /tmp/ai_hot.log 2>&1
```

## 静态站（旁路发布）

`out/` 不进 git。要上网时手动归档 → 本地预览 → push（Actions 部署 Cloudflare）。

```bash
# 1) 按 UTC 日归档到 content/digests/YYYY-MM-DD.{en,zh}.md（同日覆盖）
python -m src.publish
# 指定日期：python -m src.publish --day 2026-09-10

# 2) 本地构建预览
python -m src.site_build
# 打开 public/index.html 、 public/zh/index.html

# 3) 手动提交并推送（触发 Actions）
git add content/digests
git commit -m "content: archive digest YYYY-MM-DD"
git push
```

### Cloudflare 一次性配置

1. Cloudflare Dashboard → Workers & Pages → Create → 项目名 `ai-hot-digest`
2. GitHub repo secrets：
   - `CLOUDFLARE_API_TOKEN`（Pages 编辑权限）
   - `CLOUDFLARE_ACCOUNT_ID`
3. Workflow：`.github/workflows/deploy-cloudflare.yml`（`content/**` 或站点代码变更时构建并部署）
4. 先用 `*.pages.dev`；自定义域后绑

**不做：** GitHub Pages 主站、自动 `git push`（后续再上）。

## 配置

- 业务阈值 / RSS：`config.yaml`（可进 git）
- 密钥 / 环境：`.env`（勿提交）
- Anthropic 无官方 RSS，当前用社区镜像，可在 `config.yaml` 替换

## 质量闭环

```bash
pytest
mypy src
ruff check src && ruff format --check src
```

## v1 非目标

推送、Reddit、口播/数字人、发帖（YT/抖音/小红书）、接 ai_host、真实 affiliate CTA。

## 当前扫描源

均在 `config.yaml`，可随时增删：

| 源 | 平台 / 站点 | 入口 |
|---|---|---|
| HN | Hacker News | Firebase API Top 30（`score≥100` 且 `comments≥20`） |
| RSS | OpenAI News | https://openai.com/news/rss.xml |
| RSS | Google AI Blog | https://blog.google/innovation-and-ai/technology/ai/rss/ |
| RSS | Google DeepMind Blog | https://deepmind.google/blog/rss.xml |
| RSS | Anthropic News（社区镜像） | https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml |
| RSS | Hugging Face Blog | https://huggingface.co/blog/feed.xml |
| RSS | 量子位（关键词过滤） | https://www.qbitai.com/feed |

关键词（仅 `qbitai`）：见 `config.yaml` 中该 feed 的 `keywords`（MiniMax / Seedance / Kimi / 通义 等）。

**未扫（后置）：** Reddit、X/Twitter、Seed/MiniMax 官方 HTML、国内热搜、推送渠道。
