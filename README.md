# Arxiv Intelligence System

An AI-powered research monitoring platform that fetches papers from arXiv, Papers With Code, and Semantic Scholar, analyzes them with Claude, and delivers beautiful digests and deep research surveys — all from the command line.

## Features

- **Daily / Weekly / Monthly Digests** — beautiful HTML reports with top papers, breakthrough highlights, and trend analysis
- **Live Area Surveys** — search arXiv across all time, weight by citation impact, synthesize with Claude (`arxiv survey "event cameras"`)
- **Direction Analysis** — deep profile of any research direction: status (emerging/stable/declining), open problems, milestones, worthiness score
- **Researcher Profiles** — live arXiv author search + Claude-generated impact rating (1–10)
- **Research Q&A** — ask any question, get a cited answer backed by live arXiv papers
- **Semantic Search** — local paper database with AI embedding-based search (sentence-transformers)
- **Citation-aware ranking** — blends recency and Semantic Scholar citation counts by paper age

All live-search commands use a **70% live arXiv / 20% Claude knowledge / 10% local DB** strategy, so you get up-to-date results even on a fresh install.

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/arxiv-intel.git
cd arxiv-intel

# Create a conda environment (Python 3.10+)
conda create -n arxiv-intel python=3.10 -y
conda activate arxiv-intel

# Install dependencies
pip install -e .

# Optional: semantic search (adds ~200 MB model download on first use)
conda install -c conda-forge sentence-transformers -y
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

Or use the interactive setup command:

```bash
arxiv setup
```

### 3. Fetch your first papers

```bash
# Pull the last 7 days of AI/CV/graphics papers
arxiv fetch

# Build semantic search index (run once after first fetch)
arxiv embed
```

### 4. Start exploring

```bash
# Today's digest
arxiv report

# Weekly or monthly
arxiv report --period weekly
arxiv report --period monthly

# Survey any research area (searches arXiv live, all years)
arxiv survey "event cameras"
arxiv survey "neural path guiding"
arxiv survey "diffusion models for 3D"

# Deep-dive a research direction with live arXiv search
arxiv direction "event-based optical flow"

# Ask a research question
arxiv ask "What are the main challenges in neuromorphic computing?"

# Look up a researcher (live arXiv author search + impact rating)
arxiv professor "Davide Scaramuzza"

# Semantic search your local DB
arxiv search "spiking neural networks optical flow"
```

---

## All Commands

| Command | Description |
|---|---|
| `arxiv fetch` | Fetch latest papers from arXiv, PwC, and Semantic Scholar |
| `arxiv embed` | Build semantic search index (run once after fetch) |
| `arxiv report [--period daily\|weekly\|monthly]` | Generate research digest |
| `arxiv survey "<area>"` | Comprehensive live arXiv survey of any area |
| `arxiv direction "<name>"` | Deep analysis of a research direction |
| `arxiv ask "<question>"` | Research Q&A with cited live papers |
| `arxiv professor "<name>"` | Researcher profile + impact rating |
| `arxiv search "<query>"` | Semantic search local paper DB |
| `arxiv knowledge` | Browse analyzed directions |
| `arxiv analyze-all-directions` | Batch re-analyze all directions in local DB |
| `arxiv stats` | Database statistics |
| `arxiv web` | Launch web dashboard (requires uvicorn) |
| `arxiv tui` | Terminal UI (requires textual) |
| `arxiv setup` | Save API key to `.env` |

---

## Configuration

Edit `config.yaml` to customize what categories and queries to monitor:

```yaml
categories:
  - cs.AI
  - cs.LG
  - cs.CV
  - cs.GR
  - eess.IV

custom_queries:
  - event camera
  - neuromorphic
  - DVS

max_papers_per_run: 200
claude_model: claude-sonnet-4-6
report_dir: ./reports
db_path: ./data/papers.db
schedule_time: "08:00"
```

---

## Data Sources

| Source | Used for |
|---|---|
| [arXiv](https://arxiv.org) | Primary paper source — categories + custom queries |
| [Papers With Code](https://paperswithcode.com) | Code repository links |
| [Semantic Scholar](https://www.semanticscholar.org) | Citation counts, author influence |

A free Semantic Scholar API key is recommended to avoid rate limiting:
[https://www.semanticscholar.org/product/api](https://www.semanticscholar.org/product/api)

---

## Automating Daily Digests

Add to your crontab (`crontab -e`) to run every day at 8 AM:

```cron
0 8 * * * /path/to/conda/envs/arxiv-intel/bin/arxiv fetch && /path/to/conda/envs/arxiv-intel/bin/arxiv report
```

Or use a launchd plist on macOS (see `USER_GUIDE.md` for details).

---

## Requirements

- Python 3.9+
- Anthropic API key (required for all AI features)
- Semantic Scholar API key (optional, for higher citation-data rate limits)

Core Python dependencies (see `requirements.txt`):

```
arxiv, anthropic, rich, click, jinja2, requests, pyyaml
```

Optional:
- `sentence-transformers` — semantic search
- `fastapi` + `uvicorn` — web dashboard
- `textual` — terminal UI

---

## License

MIT
