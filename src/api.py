import os
import json
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.config import settings
from src.github_sync import (
    fetch_github_stack_profile,
    add_custom_dependency,
    remove_dependency,
    bulk_remove_dependencies,
    restore_dependency,
    bulk_restore_dependencies,
    clean_utility_noise,
    update_feed_preferences,
    reset_feed_preferences,
    update_user_city
)
from src.feed_ingestion import ingest_all_feeds, FeedIngestor
from src.consensus_engine import consensus_deduplicate
from src.analyzer import analyze_technical_content, TechAnalyzer, classify_report_category
from src.rag_store import store_in_rag, search_rag, LocalRAGStore
from src.notifier import notify_report, Notifier
from src.events_ingestion import ingest_tech_events, TechEvent

logger = logging.getLogger("dev-intel-watchdog.api")

app = FastAPI(
    title="Developer Intelligence & Security Watchdog API",
    description="REST backend for dynamic stack profiling, custom stack management, consensus feed aggregation, Gemini security analysis, tech events/hackathons, and local RAG search.",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

class DependencyPayload(BaseModel):
    dependency: str

class BulkDependencyPayload(BaseModel):
    dependencies: List[str]

class FeedPreferencesPayload(BaseModel):
    preferences: Dict[str, bool]

class CityPayload(BaseModel):
    city: str

def run_watchdog_pipeline():
    """Background worker function for non-blocking feed ingestion and analysis."""
    try:
        logger.info("Starting background watchdog feed ingestion pipeline...")
        raw_items = ingest_all_feeds()
        deduped = consensus_deduplicate(raw_items)
        
        analyzer = TechAnalyzer()
        notifier = Notifier()
        analyzed_reports = []

        for item in deduped[:15]:
            report = analyzer.analyze_item(item)
            store_in_rag(report)
            notify_report(report)
            analyzed_reports.append(report)

        notifier.save_digest_file(analyzed_reports)
        logger.info(f"Background watchdog pipeline completed successfully. Processed {len(analyzed_reports)} items.")
    except Exception as e:
        logger.error(f"Error in background watchdog execution: {e}")

def run_events_pipeline():
    """Background worker for fetching and storing hackathons, webinars, and tech events."""
    try:
        logger.info("Starting background tech events & hackathons ingestion pipeline...")
        events = ingest_tech_events()
        store = LocalRAGStore()
        for e in events:
            store.store_event(e)
        logger.info(f"Background events pipeline completed successfully. Stored {len(events)} tech events.")
    except Exception as e:
        logger.error(f"Error in background events execution: {e}")

@app.get("/")
def read_root():
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "status": "online",
        "service": "Autonomous Developer Intelligence & Security Watchdog",
        "docs_url": "/docs"
    }

@app.get("/api/stack")
def get_stack_profile():
    if os.path.exists(settings.stack_context_path):
        try:
            with open(settings.stack_context_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading stack context: {e}")
    return fetch_github_stack_profile()

@app.post("/api/stack/sync")
def trigger_stack_sync():
    try:
        profile = fetch_github_stack_profile()
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/add")
def add_dependency_endpoint(payload: DependencyPayload):
    try:
        profile = add_custom_dependency(payload.dependency)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/remove")
def remove_dependency_endpoint(payload: DependencyPayload):
    try:
        profile = remove_dependency(payload.dependency)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/bulk-remove")
def bulk_remove_dependency_endpoint(payload: BulkDependencyPayload):
    try:
        profile = bulk_remove_dependencies(payload.dependencies)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/restore")
def restore_dependency_endpoint(payload: DependencyPayload):
    try:
        profile = restore_dependency(payload.dependency)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/bulk-restore")
def bulk_restore_dependency_endpoint(payload: BulkDependencyPayload):
    try:
        profile = bulk_restore_dependencies(payload.dependencies)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stack/clean-noise")
def clean_noise_endpoint():
    try:
        profile = clean_utility_noise()
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feed/sources")
def get_feed_sources_endpoint():
    ingestor = FeedIngestor()
    _, statuses = ingestor.get_active_feeds()
    return {"sources": list(statuses.values())}

@app.post("/api/feed/sources")
def update_feed_sources_endpoint(payload: FeedPreferencesPayload):
    try:
        profile = update_feed_preferences(payload.preferences)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feed/sources/reset")
def reset_feed_sources_endpoint():
    try:
        profile = reset_feed_preferences()
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feed")
def get_feed_reports(limit: int = 500):
    ingestor = FeedIngestor()
    active_feeds, _ = ingestor.get_active_feeds()
    enabled_sources = {f["name"] for f in active_feeds}

    store = LocalRAGStore()
    with sqlite3.connect(store.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, category, topic_signature, canonical_url, technical_summary, action_required, consensus_weight, affected_dependencies, all_sources, created_at FROM feed_reports ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()

    reports = []
    seen_titles = set()

    for r in rows:
        title_key = r[1].strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        sources_list = json.loads(r[9]) if r[9] else []
        if sources_list and not any(src in enabled_sources for src in sources_list):
            continue

        deps_list = []
        repos_map = {}
        counts_map = {}
        if r[8]:
            try:
                parsed_deps = json.loads(r[8])
                if isinstance(parsed_deps, dict):
                    deps_list = parsed_deps.get("dependencies", [])
                    repos_map = parsed_deps.get("repos_map", {})
                    counts_map = parsed_deps.get("counts", {})
                elif isinstance(parsed_deps, list):
                    deps_list = parsed_deps
            except Exception:
                pass

        cat = r[2] or classify_report_category(r[1], r[5] or "", bool(r[6]))

        reports.append({
            "id": r[0],
            "title": r[1],
            "category": cat,
            "topic_signature": r[3],
            "canonical_url": r[4],
            "technical_summary": r[5],
            "action_required": bool(r[6]),
            "consensus_weight": r[7],
            "affected_dependencies": deps_list,
            "affected_repos_map": repos_map,
            "affected_repo_counts": counts_map,
            "all_sources": sources_list,
            "created_at": r[10]
        })

        if len(reports) >= limit:
            break

    return {"reports": reports, "count": len(reports)}

@app.get("/api/events")
def get_events_endpoint(city: Optional[str] = None, event_type: Optional[str] = None):
    store = LocalRAGStore()
    events = store.get_events(city=city, event_type=event_type)
    if not events:
        run_events_pipeline()
        events = store.get_events(city=city, event_type=event_type)
    return {"events": events, "count": len(events)}

@app.post("/api/events/city")
def update_user_city_endpoint(payload: CityPayload):
    try:
        profile = update_user_city(payload.city)
        return {"status": "success", "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/run")
def trigger_events_run(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_events_pipeline)
    return {"status": "started", "message": "Events ingestion pipeline launched in background."}

@app.post("/api/watchdog/run")
def trigger_watchdog_run(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_watchdog_pipeline)
    return {
        "status": "started",
        "message": "Feed ingestion & security evaluation pipeline launched asynchronously in background."
    }

@app.get("/api/search")
def search_knowledge_base(q: str = Query(..., description="Natural language search query"), top_k: int = 5):
    try:
        results = search_rag(q, top_k=top_k)
        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_dashboard_stats():
    stack = get_stack_profile()
    ingestor = FeedIngestor()
    active_feeds, _ = ingestor.get_active_feeds()
    enabled_sources = {f["name"] for f in active_feeds}

    store = LocalRAGStore()
    total_reports = 0
    urgent_cves = 0

    try:
        with sqlite3.connect(store.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, action_required, all_sources FROM feed_reports ORDER BY created_at DESC")
            rows = cursor.fetchall()
            
            seen_titles = set()
            for r in rows:
                title_key = r[0].strip().lower()
                if title_key in seen_titles:
                    continue
                
                sources_list = json.loads(r[2]) if r[2] else []
                if sources_list and not any(src in enabled_sources for src in sources_list):
                    continue
                
                seen_titles.add(title_key)
                total_reports += 1
                if bool(r[1]):
                    urgent_cves += 1
    except Exception as e:
        logger.error(f"Error computing dashboard stats: {e}")

    events_list = store.get_events()

    return {
        "active_dependencies_count": len(stack.get("active_dependencies", [])),
        "core_languages_count": len(stack.get("core_languages", [])),
        "total_reports_ingested": total_reports,
        "urgent_cve_alerts": urgent_cves,
        "total_events_count": len(events_list),
        "user_city": stack.get("user_city", "Online / Global"),
        "last_synced": stack.get("last_synced")
    }
