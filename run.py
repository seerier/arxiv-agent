#!/usr/bin/env python3
"""Entry point for the Arxiv Intelligence System CLI.

Usage
-----
    python run.py --help
    python run.py fetch
    python run.py report
    python run.py search "event camera"
    python run.py direction "neuromorphic computing"
    python run.py ask "What are the latest breakthroughs in event cameras?"
    python run.py knowledge --emerging
    python run.py professor "Davide Scaramuzza"
    python run.py stats
    python run.py schedule
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arxiv_agent.cli import cli

if __name__ == "__main__":
    cli()
