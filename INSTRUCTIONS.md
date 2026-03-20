# Arxiv Intelligence System — User Requirements & Instructions

## Project Goal
Build a comprehensive, beautiful, fully-usable research intelligence platform that:
1. Automatically fetches, analyzes, and reports on AI/CV/graphics/event-camera papers daily
2. Provides an interactive research field query tool for deep, comprehensive analysis

## Target Research Areas
- **AI/ML**: cs.AI, cs.LG (artificial intelligence, machine learning)
- **Computer Vision**: cs.CV (computer vision, image processing)
- **Graphics**: cs.GR (computer graphics, rendering, simulation)
- **Event Cameras / Neuromorphic**: custom queries (event camera, neuromorphic, DVS, dynamic vision sensor)

## Data Sources
- arXiv API (primary)
- Papers With Code (SOTA benchmarks, code links)
- Semantic Scholar (citations, influence, author profiles)
- Conference websites: CVPR, ICCV, ECCV, SIGGRAPH, NeurIPS, ICLR, ICML
- YouTube: talks, lectures, course recordings

## Daily Report Requirements
- **Length**: ~800 words / 5 minutes to read
- **Content**: Top 5 must-read papers, 1 breakthrough highlight, trending topics, new code releases
- **Format**: Beautiful HTML file + terminal-readable output
- **Schedule**: Every morning at configurable time (default 8:00 AM)

## Output Quality Standards
- **Beautiful UI**: All outputs (HTML reports, terminal output) must be visually excellent
- **Self-contained**: HTML reports embed all CSS, include all links and references
- **Well-structured**: Clear hierarchy, navigation, sections
- **Hyperlinked**: Every paper, author, conference, code repo must be linked
- **Correct**: No hallucinated links or facts; clearly label Claude-generated analysis

## Knowledge Base Features
The knowledge base must maintain and surface:
1. **Important Works**: Seminal/landmark papers per subfield
2. **Breakthroughs Timeline**: Chronological log of paradigm shifts
3. **Novel Methods Registry**: Index of new techniques with descriptions
4. **Professor/Researcher Profiles**: Name, institution, focus, top papers
5. **Conference Calendar**: Upcoming deadlines, schedules, proceedings
6. **Talks & Courses**: YouTube lectures, online courses, workshop recordings
7. **Direction Analysis** per subfield:
   - History and overview
   - Key papers and authors
   - Open problems
   - Emerging trend score (rising/stable/declining)
   - **Worthiness Rating**: Is this direction worth pursuing? Why? What's the ceiling?
8. **Emerging Directions Radar**: Weekly momentum updates
9. **Dying Directions Log**: What's being abandoned and why

## Interactive Query Tool
Users should be able to ask natural language questions like:
- "What is the current state of event cameras?"
- "Who are the top researchers in neural rendering?"
- "What directions in CV are dying vs emerging?"
- "Give me a comprehensive intro to diffusion models"

Responses should be:
- Comprehensive (deep, not surface-level)
- Well-structured with sections
- Grounded in actual papers from the DB + Claude's knowledge
- Exported as beautiful HTML report

## CLI Commands
```
arxiv fetch              # Fetch latest papers now
arxiv report             # Generate today's digest
arxiv search <query>     # Search local paper DB
arxiv direction <name>   # Full direction analysis
arxiv professor <name>   # Researcher profile
arxiv ask <question>     # Interactive research Q&A
arxiv knowledge          # Browse knowledge base
arxiv schedule           # View/manage schedule
arxiv stats              # DB stats and overview
```

## Deliverables
After completing the system, create a `USER_GUIDE.md` at the project root that:
- Is beautifully formatted and easy to read (good use of headers, code blocks, examples)
- Teaches the user how to use every feature of the system end-to-end
- Covers: installation/setup, daily workflow, all CLI commands with examples, how to interpret reports, how to use the interactive ask feature, how to browse the knowledge base, scheduler configuration
- Includes realistic example outputs so the user knows what to expect
- Is self-contained — the user should be able to learn everything from this file alone

## Technical Preferences
- Python backend
- SQLite local database (no external DB required)
- Claude API (claude-sonnet-4-6) for all AI analysis
- Rich library for beautiful terminal output
- Beautiful HTML reports with embedded CSS
- Click for CLI
- APScheduler for daily automation
- YAML config file for all settings

## Design Aesthetic
- Reports should look like a premium research newsletter
- Terminal output should use Rich panels, tables, color coding
- HTML: clean, professional, academic — like a premium digest
- Dark mode HTML preferred for reports
- All scores/ratings visualized with bars or icons, not just numbers
