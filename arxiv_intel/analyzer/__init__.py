"""Analyzer sub-package for the Arxiv Intelligence System.

Exports
-------
ClaudeClient
    Thin wrapper around the Anthropic SDK with retry logic.
get_client
    Singleton accessor for ``ClaudeClient``.
PaperAnalyzer
    Fills in all Claude-generated analysis fields on ``Paper`` objects.
DirectionAnalyzer
    Builds ``Direction`` profiles from a corpus of related papers.
KnowledgeAnalyzer
    Higher-level knowledge mining: breakthroughs, professor profiles,
    and trend reports.
"""

from arxiv_intel.analyzer.claude_client import ClaudeClient, get_client
from arxiv_intel.analyzer.paper_analyzer import PaperAnalyzer
from arxiv_intel.analyzer.direction_analyzer import DirectionAnalyzer
from arxiv_intel.analyzer.knowledge_analyzer import KnowledgeAnalyzer

__all__ = [
    "ClaudeClient",
    "get_client",
    "PaperAnalyzer",
    "DirectionAnalyzer",
    "KnowledgeAnalyzer",
]
