"""Paths, models, prices and source lists."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "coworkers.db"
CHECKPOINT_PATH = DATA_DIR / "checkpoints.db"
PROFILE_PATH = ROOT / "profile.yaml"
SAMPLES_DIR = ROOT / "samples"

ROUTINE_MODEL = os.getenv("ROUTINE_MODEL", "gpt-5.4-nano")
EVAL_MODEL = os.getenv("EVAL_MODEL", "gpt-5.4-mini")
BUDGET_USD = float(os.getenv("BUDGET_USD", "2.00"))
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")
REASONING_HEADROOM = 2000

# USD per million tokens (input, output). Unknown models are billed at the mini rate.
PRICES = {
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
}
DEFAULT_PRICE = (0.75, 4.50)

USER_AGENT = "Mozilla/5.0 (compatible; DailyTechUpgradeAgent/0.1; student project)"
CROSSREF_AGENT = "DailyTechUpgradeAgent/0.1 (student project)"

# Daily brief
WINDOW_DAYS = 7
SHORTLIST_SIZE = 12
MIN_WORDS = 90
READING_WPM = 220
MAX_MINUTES_PER_ARTICLE = 5  # Three capped articles plus their summaries make an 18-minute session.
READING_MIN, READING_MAX = 15, 20
MAX_SUMMARY_RETRIES = 1
MAX_PER_SOURCE = 2  # Only reached when distinct sources alone can't fill the brief.

# Authority weight is used in pre-ranking.
FEEDS = [
    {"source": "OpenAI", "url": "https://openai.com/news/rss.xml", "authority": 1.0},
    {"source": "Google AI", "url": "https://blog.google/technology/ai/rss/", "authority": 0.9},
    {"source": "Google Research", "url": "https://research.google/blog/rss/", "authority": 1.0},
    {"source": "AWS Machine Learning", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "authority": 0.9},
    {"source": "AWS Architecture", "url": "https://aws.amazon.com/blogs/architecture/feed/", "authority": 1.0},
    {"source": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "authority": 1.0},
    {"source": "Microsoft Foundry", "url": "https://devblogs.microsoft.com/foundry/feed/", "authority": 0.9},
    {"source": "IEEE Spectrum", "url": "https://spectrum.ieee.org/feeds/feed.rss", "authority": 1.0},
    {"source": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml", "authority": 0.8},
    {"source": "LangGraph Releases", "url": "https://github.com/langchain-ai/langgraph/releases.atom", "authority": 0.7},
]
SITEMAPS = [
    {"source": "Anthropic", "url": "https://www.anthropic.com/sitemap.xml", "pattern": r"/(news|engineering|research)/", "authority": 1.0},
    {"source": "LangChain", "url": "https://www.langchain.com/sitemap.xml", "pattern": r"/blog/", "authority": 0.9},
]
LISTING_PAGES = [
    {"source": "IBM Research", "url": "https://research.ibm.com/blog", "pattern": r'href="(/blog/[^"#?]+)"',
     "base": "https://research.ibm.com", "authority": 1.0},
]
CROSSREF_JOURNALS = [
    {"source": "ACM CACM", "issn": "0001-0782", "authority": 1.0},
    {"source": "ACM Queue", "issn": "1542-7730", "authority": 1.0},
    {"source": "ACM Computing Surveys", "issn": "0360-0300", "authority": 0.9},
]
ARXIV_CATEGORIES = ["cs.SE", "cs.DC", "cs.DB"]

# Topic vocabulary for tagging articles without using the LLM.
TOPIC_KEYWORDS = {
    "distributed systems": ["distributed", "consensus", "replication", "raft", "partition", "fault tolerance", "cluster", "kubernetes"],
    "backend engineering": ["backend", "api", "microservice", "server", "grpc", "rest api", "latency"],
    "cloud infrastructure": ["cloud", "aws", "azure", "gcp", "serverless", "lambda", "infrastructure", "terraform"],
    "databases": ["database", "sql", "postgres", "index", "query", "transaction", "storage engine", "vector store"],
    "concurrency and performance": ["concurrency", "thread", "parallel", "performance", "throughput", "benchmark", "scheduler"],
    "software architecture": ["architecture", "design pattern", "system design", "scalab", "monolith", "event-driven"],
    "testing and reliability": ["testing", "reliability", "observability", "incident", "ci/cd", "monitoring", "evaluation"],
    "security": ["security", "vulnerability", "attack", "authentication", "encryption", "prompt injection"],
    "ai engineering": ["llm", "rag", "retrieval", "inference", "embedding", "prompt", "fine-tuning", "model serving"],
    "agents": ["agent", "agentic", "langgraph", "tool use", "mcp", "multi-agent", "orchestration"],
    "machine learning": ["machine learning", "neural", "training", "dataset", "transformer", "deep learning"],
}

# Skill taxonomy for the coach, and which daily-brief topic each skill feeds.
SKILLS = [
    "dsa", "system-design", "concurrency", "databases-sql", "distributed-systems", "cloud-aws",
    "networking", "os-internals", "api-design", "testing-ci", "python", "cpp", "java",
    "javascript-react", "ai-engineering", "behavioral",
]
SKILL_TO_TOPIC = {
    "system-design": "software architecture",
    "concurrency": "concurrency and performance",
    "databases-sql": "databases",
    "distributed-systems": "distributed systems",
    "cloud-aws": "cloud infrastructure",
    "api-design": "backend engineering",
    "testing-ci": "testing and reliability",
    "ai-engineering": "ai engineering",
    "os-internals": "concurrency and performance",
    "networking": "backend engineering",
}

# Coach
QUESTIONS_PER_SESSION = 4
MAX_FOLLOW_UPS = 1  # Two made sessions run long, and the second often repeated the first.
GREENHOUSE_BOARDS = ["anthropic", "stripe", "databricks", "cloudflare", "figma", "discord", "airbnb"]
LEVER_BOARDS = ["palantir", "spotify"]
ASHBY_BOARDS = ["openai", "notion", "ramp"]
SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
HN_SHOW_FEED = "https://hnrss.org/show?points=50"
