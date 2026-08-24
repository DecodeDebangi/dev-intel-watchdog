import os
import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests
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

KNOWN_EVENT_TOPICS = [
    "python", "javascript", "react", "devops", "security",
    "ai", "android", "ios", "general", "graphql", "cloud"
]

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

class EventsIngestor:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.gemini_api_key
        self.client = None
        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client for events ingestion: {e}")

    def _clean_html(self, text: str) -> str:
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', text)
        return ' '.join(clean.split())

    def _normalize_city_name(self, raw_city: Optional[str]) -> str:
        if not raw_city:
            return "Online"
        c = raw_city.strip().lower()
        if "bangalore" in c or "bengaluru" in c:
            return "Bengaluru"
        if "san francisco" in c or "sf" in c or "bay area" in c or "san jose" in c:
            return "San Francisco"
        if "delhi" in c or "noida" in c or "gurugram" in c or "gurgaon" in c:
            return "Delhi"
        if "hyderabad" in c:
            return "Hyderabad"
        if "mumbai" in c:
            return "Mumbai"
        if "chennai" in c:
            return "Chennai"
        if "pune" in c:
            return "Pune"
        if "london" in c:
            return "London"
        if "new york" in c or "nyc" in c:
            return "New York"
        if "singapore" in c:
            return "Singapore"
        if "tokyo" in c:
            return "Tokyo"
        if "berlin" in c:
            return "Berlin"
        if "paris" in c:
            return "Paris"
        if "chicago" in c:
            return "Chicago"
        if "seattle" in c:
            return "Seattle"
        if "austin" in c:
            return "Austin"
        
        # Clean state/country suffixes e.g. "San Francisco, CA" -> "San Francisco"
        clean = raw_city.split(",")[0].strip()
        return clean

    def _determine_event_type(self, title: str, summary: str, is_online: bool) -> str:
        text = f"{title} {summary}".lower()
        if "hackathon" in text or "buildathon" in text or "challenge" in text:
            return "hackathon"
        if "webinar" in text or "workshop" in text or "livestream" in text or "masterclass" in text:
            return "webinar"
        if "meetup" in text or "user group" in text or "community" in text:
            return "local_meetup"
        if not is_online or "conference" in text or "summit" in text or "pycon" in text or "jsconf" in text or "droidcon" in text:
            return "local_meetup" if not is_online else "global_conference"
        return "global_conference"

    def _extract_stack_tags(self, title: str, summary: str) -> List[str]:
        combined = f"{title} {summary}".lower()
        known_stack = [
            "react", "react-dom", "next", "express", "fastapi", "python",
            "typescript", "javascript", "node", "django", "flask", "ai",
            "openai", "pydantic", "tailwindcss", "vite", "docker", "postgres",
            "android", "ios", "flutter", "cloud", "security", "graphql"
        ]
        found = [kw for kw in known_stack if re.search(r'\b' + re.escape(kw) + r'\b', combined)]
        return sorted(list(set(found)))

    def fetch_real_tech_conferences(self) -> List[TechEvent]:
        """Fetch 100% REAL-WORLD global tech events, conferences, and meetups."""
        events: List[TechEvent] = []
        seen_urls = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        for topic in KNOWN_EVENT_TOPICS:
            url = f"https://raw.githubusercontent.com/tech-conferences/conference-data/main/conferences/2026/{topic}.json"
            try:
                res = requests.get(url, headers=headers, timeout=6)
                if res.status_code != 200:
                    continue
                
                raw_list = res.json()
                if not isinstance(raw_list, list):
                    continue

                for item in raw_list:
                    name = item.get("name", "").strip()
                    event_url = item.get("url", "").strip()
                    if not name or not event_url or event_url in seen_urls:
                        continue

                    seen_urls.add(event_url)

                    is_online = bool(item.get("online", False))
                    raw_city = item.get("city", "")
                    country = item.get("country", "")
                    start_date = item.get("startDate", "2026")
                    
                    city_name = "Online" if is_online and not raw_city else self._normalize_city_name(raw_city)

                    summary_parts = []
                    if country and not is_online:
                        summary_parts.append(f"In-person developer event hosted in {city_name}, {country}.")
                    elif is_online:
                        summary_parts.append("Global virtual developer summit accessible worldwide.")
                    
                    if item.get("cfpUrl"):
                        summary_parts.append("Call for Proposals (CFP) is active for speakers.")

                    summary = " ".join(summary_parts) if summary_parts else f"Premier developer gathering for {topic.upper()} professionals."

                    e_type = self._determine_event_type(name, summary, is_online)
                    tags = self._extract_stack_tags(f"{name} {topic}", summary)
                    item_id = hashlib.sha256(f"{name}:{event_url}".encode('utf-8')).hexdigest()[:16]

                    events.append(TechEvent(
                        id=item_id,
                        title=name,
                        event_type=e_type,
                        is_virtual=is_online,
                        city_location=city_name,
                        event_date=start_date,
                        url=event_url,
                        stack_tags=tags,
                        summary=summary
                    ))
            except Exception as e:
                logger.error(f"Error fetching real events for topic '{topic}': {e}")

        logger.info(f"Ingested {len(events)} 100% REAL-WORLD tech events & conferences.")
        return events

    def fetch_events(self) -> List[TechEvent]:
        # Ingest 100% Real-World tech events
        return self.fetch_real_tech_conferences()

def ingest_tech_events() -> List[TechEvent]:
    ingestor = EventsIngestor()
    return ingestor.fetch_events()
