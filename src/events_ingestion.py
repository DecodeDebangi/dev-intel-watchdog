import os
import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import feedparser
from pydantic import BaseModel, Field

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.config import settings

logger = logging.getLogger("dev-intel-watchdog.events_ingestion")

class TechEvent(BaseModel):
    id: str
    title: str
    event_type: str  # 'hackathon', 'webinar', 'local_meetup', 'global_conference'
    is_virtual: bool = True
    city_location: Optional[str] = "Online"
    event_date: str = "Upcoming"
    url: str
    stack_tags: List[str] = []
    summary: str

KNOWN_EVENT_FEEDS = [
    {
        "name": "Devpost Hackathons",
        "url": "https://devpost.com/hackathons.rss",
        "default_type": "hackathon"
    },
    {
        "name": "Global Tech Conferences & Events",
        "url": "https://tldr.tech/tech/feed",
        "default_type": "global_conference"
    }
]

SAMPLE_EVENTS = [
    {
        "title": "Global AI & LLM Innovation Hackathon 2026",
        "event_type": "hackathon",
        "is_virtual": True,
        "city_location": "Online",
        "event_date": "2026-09-15",
        "url": "https://devpost.com/hackathons",
        "stack_tags": ["python", "fastapi", "ai", "pydantic", "openai"],
        "summary": "Build cutting-edge autonomous AI agents and vector RAG applications. $50,000 in total prizes!"
    },
    {
        "title": "React & Next.js 15 Full-Stack Summit",
        "event_type": "webinar",
        "is_virtual": True,
        "city_location": "Online",
        "event_date": "2026-09-20",
        "url": "https://reactsummit.com",
        "stack_tags": ["react", "next", "typescript", "javascript"],
        "summary": "Deep dive into Server Actions, Partial Prerendering, and performance optimizations for modern Web apps."
    },
    {
        "title": "Bengaluru Dev Community Tech Meetup",
        "event_type": "local_meetup",
        "is_virtual": False,
        "city_location": "Bengaluru",
        "event_date": "2026-09-10",
        "url": "https://meetup.com",
        "stack_tags": ["python", "react", "node", "express"],
        "summary": "Local networking, lightning tech talks, and live coding demos with developer peers in Bengaluru."
    },
    {
        "title": "San Francisco AI Developer Conference",
        "event_type": "local_meetup",
        "is_virtual": False,
        "city_location": "San Francisco",
        "event_date": "2026-09-28",
        "url": "https://meetup.com",
        "stack_tags": ["python", "fastapi", "ai"],
        "summary": "In-person developer summit featuring keynotes from leading AI researchers and open-source maintainers."
    },
    {
        "title": "PyCon Global Developer Conference 2026",
        "event_type": "global_conference",
        "is_virtual": True,
        "city_location": "Global",
        "event_date": "2026-10-05",
        "url": "https://pycon.org",
        "stack_tags": ["python", "django", "fastapi"],
        "summary": "The premier annual conference for the Python programming language community worldwide."
    }
]

class EventsIngestor:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.gemini_api_key
        self.client = None
        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client for events ingestion: {e}")

    def _determine_event_type(self, title: str, summary: str, default_type: str) -> str:
        text = f"{title} {summary}".lower()
        if "hackathon" in text or "buildathon" in text or "challenge" in text:
            return "hackathon"
        if "webinar" in text or "workshop" in text or "livestream" in text or "masterclass" in text:
            return "webinar"
        if "meetup" in text or "gathering" in text or "user group" in text:
            return "local_meetup"
        if "conference" in text or "summit" in text or "pycon" in text or "jsconf" in text:
            return "global_conference"
        return default_type

    def _extract_stack_tags(self, title: str, summary: str) -> List[str]:
        combined = f"{title} {summary}".lower()
        known_stack = [
            "react", "react-dom", "next", "express", "fastapi", "python",
            "typescript", "javascript", "node", "django", "flask", "ai",
            "openai", "pydantic", "tailwindcss", "vite", "docker", "postgres"
        ]
        found = [kw for kw in known_stack if re.search(r'\b' + re.escape(kw) + r'\b', combined)]
        return sorted(list(set(found)))

    def fetch_events(self) -> List[TechEvent]:
        events: List[TechEvent] = []

        # 1. Load sample curated events first
        for s in SAMPLE_EVENTS:
            item_id = hashlib.sha256(f"{s['title']}:{s['url']}".encode('utf-8')).hexdigest()[:16]
            events.append(TechEvent(
                id=item_id,
                title=s["title"],
                event_type=s["event_type"],
                is_virtual=s["is_virtual"],
                city_location=s["city_location"],
                event_date=s["event_date"],
                url=s["url"],
                stack_tags=s["stack_tags"],
                summary=s["summary"]
            ))

        # 2. Ingest live RSS feeds
        for feed in KNOWN_EVENT_FEEDS:
            name = feed["name"]
            url = feed["url"]
            def_type = feed["default_type"]
            
            try:
                parsed = feedparser.parse(url)
                for entry in parsed.entries[:8]:
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", "")).strip()
                    link = entry.get("link", url)

                    if not title:
                        continue

                    e_type = self._determine_event_type(title, summary, def_type)
                    tags = self._extract_stack_tags(title, summary)
                    item_id = hashlib.sha256(f"{name}:{title}:{link}".encode('utf-8')).hexdigest()[:16]

                    is_virt = "online" in f"{title} {summary}".lower() or "virtual" in f"{title} {summary}".lower() or e_type in ["hackathon", "webinar"]

                    events.append(TechEvent(
                        id=item_id,
                        title=title,
                        event_type=e_type,
                        is_virtual=is_virt,
                        city_location="Online" if is_virt else "Global",
                        event_date="Upcoming 2026",
                        url=link,
                        stack_tags=tags,
                        summary=summary[:250] + "..." if len(summary) > 250 else summary
                    ))
            except Exception as e:
                logger.error(f"Error fetching event feed '{name}': {e}")

        logger.info(f"Ingested {len(events)} tech events, hackathons, and webinars.")
        return events

def ingest_tech_events() -> List[TechEvent]:
    ingestor = EventsIngestor()
    return ingestor.fetch_events()
