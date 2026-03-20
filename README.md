<div align="center">

# arXiv Autopilot

**AI-powered research intelligence, entirely from your terminal.**

[![PyPI](https://img.shields.io/pypi/v/arxiv-autopilot?color=gold&label=PyPI)](https://pypi.org/project/arxiv-autopilot/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Powered by Claude](https://img.shields.io/badge/powered%20by-Claude-orange)](https://www.anthropic.com/claude)

<!-- DEMO GIF — replace with your recording -->
![demo](assets/demo.gif)

</div>

---

arXiv Autopilot monitors arXiv, Papers With Code, and Semantic Scholar,
analyses papers with Claude, and lets you explore the research landscape
through a set of focused CLI commands — no GUI, no subscriptions, no noise.

```bash
pip install arxiv-autopilot
arxiv setup          # paste your Anthropic API key once
arxiv fetch          # pull today's papers
arxiv recommend "3D gaussian splatting"   # find what to work on next
```

---

## What it does

| Command | What you get |
|---|---|
| `arxiv recommend "field"` | Top N research topics ranked by momentum × novelty — with a suggested research angle for each |
| `arxiv survey "topic"` | Full survey across all of arXiv history, citation-weighted, synthesised by Claude |
| `arxiv direction "topic"` | Worthiness score, status (emerging / stable / declining), open problems, key papers |
| `arxiv ask "question"` | Deep answer grounded in live arXiv papers, with citations |
| `arxiv professor "name"` | Researcher profile: bio, impact rating 1–10, top papers |
| `arxiv report` | Daily / weekly / monthly HTML digest of your configured field |
| `arxiv topic save "name"` | Save any interesting topic to your personal list |

Every command searches arXiv **live** across all years, enriches results with
Semantic Scholar citation counts, then lets Claude synthesise the output.
Results open as **beautiful HTML reports** in your browser automatically.

---

## Install

```bash
# Core — all main features
pip install arxiv-autopilot

# With semantic search (embedding-based local search)
pip install "arxiv-autopilot[semantic-search]"

# Everything
pip install "arxiv-autopilot[all]"
```

Requires **Python 3.9+** and an [Anthropic API key](https://console.anthropic.com/).
A free [Semantic Scholar API key](https://www.semanticscholar.org/product/api) is optional but recommended.

---

## Quick start

```bash
# 1. Save your API key (only needed once)
arxiv setup

# 2. Pull papers from your configured field
arxiv fetch

# 3. Find what to work on next
arxiv recommend "neural rendering and 3D reconstruction"

# 4. Deep-dive a direction
arxiv direction "3D gaussian splatting"

# 5. Ask a research question
arxiv ask "What are the main open problems in real-time NeRF rendering?"

# 6. Survey an area
arxiv survey "diffusion models for inverse problems"

# 7. Look up a researcher
arxiv professor "Andreas Geiger"
```

---

## Topic recommendations

```
$ arxiv recommend "event-based vision" -n 5
```

<div align="center">

<!-- RECOMMEND SCREENSHOT — replace with your screenshot -->
![recommend](assets/recommend.png)

</div>

Each topic card shows three scores:

- **Momentum** — how fast this sub-topic is growing right now
- **Novelty** — how much open territory remains (no dominant paper yet)
- **Opportunity** = momentum × novelty — the sweet spot for new contributions

Click **★ Save Topic** in the HTML report, or:

```bash
arxiv topic save "Neuromorphic Tokenization for Event Streams"
arxiv topic list
```

---

## Research direction deep-dive

```
$ arxiv direction "flow matching"
```

<div align="center">

<!-- DIRECTION SCREENSHOT -->
![direction](assets/direction.png)

</div>

Searches arXiv live, fetches citation counts from Semantic Scholar, then produces:

- **Status** — emerging / stable / declining / dead
- **Worthiness score** 1–10 with reasoning
- **Open problems** you could tackle
- **Milestones timeline**
- **HTML report** saved to `reports/directions/`

---

## Configuration

Edit `config.yaml` to set which arXiv categories and queries to monitor:

```yaml
categories:
  - cs.CV
  - cs.AI
  - cs.LG

custom_queries:
  - diffusion models
  - vision transformers
  - neural radiance field

claude_model: claude-sonnet-4-6
max_papers_per_run: 200
report_dir: ./reports
db_path: ./data/papers.db
```

---

## All commands

```
arxiv fetch                          Pull latest papers (arXiv + PwC + S2)
arxiv report [--period weekly]       HTML digest for your configured field
arxiv recommend "field"              Topic recommendations with opportunity scores
arxiv survey "topic"                 Full survey across all arXiv history
arxiv direction "name"               Deep direction analysis
arxiv ask "question"                 Research Q&A with cited live papers
arxiv professor "name"               Researcher profile + impact rating
arxiv topic save "name"              Save an interesting topic
arxiv topic list                     List your saved topics
arxiv topic note <id> "text"         Add notes to a saved topic
arxiv search "query"                 Semantic search local paper DB
arxiv embed                          Build local semantic search index
arxiv knowledge                      Browse analysed directions
arxiv stats                          Database statistics
arxiv web                            Web dashboard (requires uvicorn)
arxiv tui                            Terminal UI (requires textual)
arxiv setup                          Save API key to .env
```

---

## Automating daily digests

Add to your crontab (`crontab -e`) to fetch and report every day at 8 AM:

```bash
0 8 * * * arxiv fetch && arxiv report
```

---

## Data sources

| Source | Used for |
|---|---|
| [arXiv](https://arxiv.org) | Papers — categories + custom keyword queries |
| [Papers With Code](https://paperswithcode.com) | Code repository links |
| [Semantic Scholar](https://www.semanticscholar.org) | Citation counts, influential citations |

---

## Requirements

- Python 3.9+
- [Anthropic API key](https://console.anthropic.com/) — for all AI features
- [Semantic Scholar API key](https://www.semanticscholar.org/product/api) — optional, avoids rate limits

---

## License

MIT
