import os
import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
import feedparser
from pydantic import BaseModel, Field

from src.config import settings

logger = logging.getLogger("dev-intel-watchdog.feed_ingestion")

class FeedItem(BaseModel):
    id: str
    title: str
    topic_signature: str
    source: str
    text: str
    url: str
    published_at: str

ALL_KNOWN_FEEDS = [
    {
        "name": "GitHub Security Advisories",
        "url": "https://github.blog/category/security/feed/",
        "category": "security",
        "ecosystems": ["all"]
    },
    {
        "name": "NVD Vulnerability Database",
        "url": "https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss.xml",
        "category": "security",
        "ecosystems": ["all"]
    },
    {
        "name": "PyPI Package Security Updates",
        "url": "https://pypi.org/rss/updates.xml",
        "category": "releases",
        "ecosystems": ["python"]
    },
    {
        "name": "Node.js Security Releases",
        "url": "https://nodejs.org/en/feed/blog.xml",
        "category": "security",
        "ecosystems": ["javascript", "typescript", "node"]
    },
    {
        "name": "TLDR Web Dev & Tech",
        "url": "https://tldr.tech/tech/feed",
        "category": "newsletter",
        "ecosystems": ["all"]
    }
]

class FeedIngestor:
    def __init__(self, stack_path: str = None):
        self.stack_path = stack_path or settings.stack_context_path

    def load_stack_context(self) -> dict:
        if os.path.exists(self.stack_path):
            try:
                with open(self.stack_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading stack context: {e}")
        return {
            "core_languages": ["JavaScript", "Python"],
            "active_dependencies": ["react", "express", "fastapi"],
            "feed_preferences": {}
        }

    def get_active_feeds(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        stack = self.load_stack_context()
        languages = [l.lower() for l in stack.get("core_languages", [])]
        active_deps = [d.lower() for d in stack.get("active_dependencies", [])]
        prefs = stack.get("feed_preferences", {})

        has_python = "python" in languages or any("py" in d for d in active_deps)
        has_node = any(l in languages for l in ["javascript", "typescript", "node"]) or any(d in active_deps for d in ["react", "express", "node", "next"])

        active_feeds = []
        statuses = {}

        for feed in ALL_KNOWN_FEEDS:
            name = feed["name"]
            ecosystems = feed["ecosystems"]

            # Determine auto-detected state
            auto_enabled = True
            reason = "Universal developer feed"

            if "python" in ecosystems:
                auto_enabled = has_python
                reason = "Auto-enabled (Python detected in stack)" if has_python else "Auto-muted (No Python detected in active stack)"
            elif "javascript" in ecosystems or "node" in ecosystems:
                auto_enabled = has_node
                reason = "Auto-enabled (JS/Node detected in stack)" if has_node else "Auto-muted (No JS/Node detected in active stack)"

            # User manual override preference
            is_enabled = prefs.get(name, auto_enabled)
            is_overridden = name in prefs

            statuses[name] = {
                "name": name,
                "enabled": is_enabled,
                "auto_enabled": auto_enabled,
                "is_overridden": is_overridden,
                "reason": f"Manual override ({'ON' if is_enabled else 'OFF'})" if is_overridden else reason,
                "ecosystems": ecosystems
            }

            if is_enabled:
                active_feeds.append(feed)

        return active_feeds, statuses

    def _is_item_ecosystem_relevant(self, title: str, text: str, user_languages: List[str]) -> bool:
        """Filters out stories for completely un-used language ecosystems (e.g. Ruby, PHP, Rust, Go)."""
        combined = f"{title.lower()} {text.lower()}"
        
        # Unused ecosystem keywords
        ecosystem_map = {
            "ruby": ["ruby", "rails", "gemfile"],
            "php": ["php", "laravel", "composer.json", "wordpress"],
            "rust": ["rust", "cargo.toml", "crates.io"],
            "go": ["golang", "go.mod"],
            "java": ["java", "maven", "gradle", "spring boot"]
        }

        user_langs_lower = [l.lower() for l in user_languages]

        for eco, keywords in ecosystem_map.items():
            if eco not in user_langs_lower:
                for kw in keywords:
                    if re.search(r'\b' + re.escape(kw) + r'\b', combined):
                        logger.info(f"Muting feed item '{title[:50]}...' (Targets {eco}, which is not in active user languages {user_languages})")
                        return False

        return True

    def _generate_topic_signature(self, title: str, text: str) -> str:
        combined = f"{title} {text}".lower()
        clean_words = re.findall(r'\b[a-z0-9\-\.]{3,}\b', combined)
        
        cve_match = re.search(r'cve-\d{4}-\d+', combined)
        if cve_match:
            return cve_match.group(0)
            
        tech_keywords = [w for w in clean_words if w in [
            "react", "react-dom", "next", "nextjs", "express", "fastapi", 
            "pydantic", "python", "typescript", "javascript", "node", "npm", 
            "django", "flask", "tailwindcss", "vite", "vulnerability", "cve"
        ]]
        
        if tech_keywords:
            return "-".join(sorted(list(set(tech_keywords[:3]))))
            
        fallback_str = "-".join(clean_words[:5])
        return hashlib.md5(fallback_str.encode('utf-8')).hexdigest()[:12]

    def fetch_feed_items(self) -> List[FeedItem]:
        items: List[FeedItem] = []
        active_feeds, _ = self.get_active_feeds()
        stack = self.load_stack_context()
        user_languages = stack.get("core_languages", ["JavaScript", "Python"])
        
        for feed_config in active_feeds:
            name = feed_config["name"]
            url = feed_config["url"]
            logger.info(f"Ingesting feed: {name} ({url})")
            
            try:
                parsed = feedparser.parse(url)
                for entry in parsed.entries[:10]:
                    title = entry.get("title", "No Title").strip()
                    summary = entry.get("summary", entry.get("description", "")).strip()
                    link = entry.get("link", url)
                    published = entry.get("published", entry.get("updated", datetime.now(timezone.utc).isoformat()))
                    
                    if not self._is_item_ecosystem_relevant(title, summary, user_languages):
                        continue

                    item_id = hashlib.sha256(f"{name}:{title}:{link}".encode('utf-8')).hexdigest()[:16]
                    topic_sig = self._generate_topic_signature(title, summary)
                    
                    feed_item = FeedItem(
                        id=item_id,
                        title=title,
                        topic_signature=topic_sig,
                        source=name,
                        text=summary,
                        url=link,
                        published_at=published
                    )
                    items.append(feed_item)
            except Exception as e:
                logger.error(f"Error fetching feed '{name}' ({url}): {e}")

        logger.info(f"Successfully ingested {len(items)} relevant raw feed items across {len(active_feeds)} active feeds.")
        return items

def ingest_all_feeds() -> List[FeedItem]:
    ingestor = FeedIngestor()
    return ingestor.fetch_feed_items()
