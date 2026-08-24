import sys
import argparse
import logging
import uvicorn

from src.config import settings
from src.github_sync import fetch_github_stack_profile
from src.feed_ingestion import ingest_all_feeds
from src.consensus_engine import consensus_deduplicate
from src.analyzer import analyze_technical_content
from src.rag_store import store_in_rag, search_rag
from src.notifier import notify_report, Notifier
from src.scheduler import print_cron_schedule_instructions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("dev-intel-watchdog")

def run_sync():
    print("🔄 Synchronizing GitHub Tech Stack Profile...")
    profile = fetch_github_stack_profile()
    print(f"✅ Stack Profile Synced! Active Dependencies: {len(profile.get('active_dependencies', []))}")

def run_watchdog():
    print("🚀 Ingesting multi-source tech feeds & running Consensus Engine...")
    raw_items = ingest_all_feeds()
    if not raw_items:
        print("⚠️ No raw feed items fetched. Check feed URLs.")
        return

    deduped = consensus_deduplicate(raw_items)
    print(f"🔥 Processed {len(raw_items)} raw items into {len(deduped)} deduplicated consensus reports.\n")

    for item in deduped[:10]:
        report = analyze_technical_content(item)
        store_in_rag(report)
        notify_report(report)

def run_digest():
    print("📋 Generating Daily Digest Briefing...")
    raw_items = ingest_all_feeds()
    deduped = consensus_deduplicate(raw_items)
    
    reports = []
    notifier = Notifier()
    
    for item in deduped:
        report = analyze_technical_content(item)
        reports.append(report)
        store_in_rag(report)

    notifier.save_digest_file(reports)
    print(f"✅ Saved Daily Digest with {len(reports)} items to digests directory.")

def run_search(query: str):
    print(f"🔍 Searching Local Vector RAG Store for: '{query}'...\n")
    results = search_rag(query, top_k=5)
    if not results:
        print("No matching reports found in knowledge base.")
        return

    for idx, r in enumerate(results, 1):
        score = r.get("similarity_score", 0.0)
        action_flag = "🚨 URGENT" if r.get("action_required") else "📋 ROUTINE"
        print(f"{idx}. [{action_flag}] (Relevance: {score}) {r['title']}")
        print(f"   Summary: {r['technical_summary']}")
        if r.get("affected_dependencies"):
            print(f"   Affected Stack: {', '.join(r['affected_dependencies'])}")
        print()

def run_ui():
    print(f"🛡️  Starting Web UI Dashboard at http://127.0.0.1:{settings.port}")
    uvicorn.run("src.api:app", host="127.0.0.1", port=settings.port, reload=False)

def main():
    parser = argparse.ArgumentParser(description="Autonomous Developer Intelligence & Security Watchdog")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("sync", help="Synchronize GitHub tech stack profile")
    subparsers.add_parser("watchdog", help="Run 30-min security watchdog polling & analysis")
    subparsers.add_parser("digest", help="Generate daily digest briefing")
    
    search_parser = subparsers.add_parser("search", help="Execute vector RAG search over stored intelligence")
    search_parser.add_argument("query", type=str, help="Search query string")

    subparsers.add_parser("ui", help="Launch Web UI Dashboard & API server")
    subparsers.add_parser("schedule", help="Print crontab scheduler setup instructions")

    args = parser.parse_args()

    if args.command == "sync":
        run_sync()
    elif args.command == "watchdog":
        run_watchdog()
    elif args.command == "digest":
        run_digest()
    elif args.command == "search":
        run_search(args.query)
    elif args.command == "ui":
        run_ui()
    elif args.command == "schedule":
        print_cron_schedule_instructions()
    else:
        # Default action: run watchdog and print help if no subcommands
        parser.print_help()

if __name__ == "__main__":
    main()
