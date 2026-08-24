import os
import json
import sqlite3
import math
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.config import settings
from src.analyzer import TechAnalysisResult, classify_report_category

logger = logging.getLogger("dev-intel-watchdog.rag_store")

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot / (norm_v1 * norm_v2)

class LocalRAGStore:
    def __init__(self, db_path: str = None, api_key: str = None):
        self.db_path = db_path or settings.database_path
        self.api_key = api_key or settings.gemini_api_key
        self.client = None
        
        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini embedding client: {e}")

        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feed_reports (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT,
                    topic_signature TEXT,
                    canonical_url TEXT,
                    technical_summary TEXT,
                    action_required INTEGER,
                    consensus_weight INTEGER,
                    affected_dependencies TEXT,
                    all_sources TEXT,
                    created_at TEXT,
                    embedding TEXT
                )
            """)
            # Ensure category column exists if database was created earlier
            try:
                cursor.execute("ALTER TABLE feed_reports ADD COLUMN category TEXT")
            except Exception:
                pass
            conn.commit()

    def _generate_embedding(self, text: str) -> List[float]:
        if self.client:
            try:
                res = self.client.models.embed_content(
                    model="text-embedding-004",
                    contents=text
                )
                if hasattr(res, "embedding") and hasattr(res.embedding, "values"):
                    return res.embedding.values
                elif isinstance(res, dict) and "embedding" in res:
                    return res["embedding"]["values"]
            except Exception as e:
                logger.error(f"Error generating Gemini embedding: {e}")

        vec = [0.0] * 64
        for i, char in enumerate(text.lower()):
            idx = ord(char) % 64
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def store_report(self, report: TechAnalysisResult) -> str:
        text_to_embed = f"{report.title}\n{report.technical_summary}\n{' '.join(report.affected_dependencies)}"
        embedding_vec = self._generate_embedding(text_to_embed)
        
        hash_input = f"{report.title.strip().lower()}:{report.canonical_url.strip()}"
        report_id = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:16]

        affected_payload = {
            "dependencies": report.affected_dependencies,
            "repos_map": report.affected_repos_map,
            "counts": report.affected_repo_counts
        }

        category = getattr(report, "category", classify_report_category(report.title, report.technical_summary, report.action_required))

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO feed_reports (
                    id, title, category, topic_signature, canonical_url, technical_summary,
                    action_required, consensus_weight, affected_dependencies,
                    all_sources, created_at, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_id,
                report.title,
                category,
                getattr(report, "topic_signature", ""),
                report.canonical_url,
                report.technical_summary,
                1 if report.action_required else 0,
                report.consensus_weight,
                json.dumps(affected_payload),
                json.dumps(report.all_sources),
                datetime.now(timezone.utc).isoformat(),
                json.dumps(embedding_vec)
            ))
            conn.commit()
            
        logger.info(f"Stored report '{report.title}' [{category}] in local RAG vector store.")
        return report_id

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_vec = self._generate_embedding(query)
        results: List[Tuple[float, Dict[str, Any]]] = []
        seen_titles = set()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, category, canonical_url, technical_summary, action_required, consensus_weight, affected_dependencies, all_sources, created_at, embedding FROM feed_reports ORDER BY created_at DESC")
            rows = cursor.fetchall()

            for row in rows:
                r_id, title, category, url, summary, act_req, weight, deps_json, sources_json, created_at, emb_json = row
                
                title_key = title.strip().lower()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                try:
                    item_vec = json.loads(emb_json)
                    score = cosine_similarity(query_vec, item_vec)
                except Exception:
                    score = 0.0

                deps_list = []
                repos_map = {}
                counts_map = {}

                if deps_json:
                    try:
                        parsed_deps = json.loads(deps_json)
                        if isinstance(parsed_deps, dict):
                            deps_list = parsed_deps.get("dependencies", [])
                            repos_map = parsed_deps.get("repos_map", {})
                            counts_map = parsed_deps.get("counts", {})
                        elif isinstance(parsed_deps, list):
                            deps_list = parsed_deps
                    except Exception:
                        pass

                cat = category or classify_report_category(title, summary or "", bool(act_req))

                item_dict = {
                    "id": r_id,
                    "title": title,
                    "category": cat,
                    "canonical_url": url,
                    "technical_summary": summary,
                    "action_required": bool(act_req),
                    "consensus_weight": weight,
                    "affected_dependencies": deps_list,
                    "affected_repos_map": repos_map,
                    "affected_repo_counts": counts_map,
                    "all_sources": json.loads(sources_json) if sources_json else [],
                    "created_at": created_at,
                    "similarity_score": round(score, 4)
                }
                results.append((score, item_dict))

        results.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in results[:top_k]]

    def cleanup_duplicates(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM feed_reports 
                WHERE rowid NOT IN (
                    SELECT MAX(rowid) 
                    FROM feed_reports 
                    GROUP BY LOWER(TRIM(title))
                )
            """)
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Database cleanup removed {deleted_count} duplicate feed report entries.")
            return deleted_count

def store_in_rag(report: TechAnalysisResult) -> str:
    store = LocalRAGStore()
    return store.store_report(report)

def search_rag(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    store = LocalRAGStore()
    return store.search(query, top_k=top_k)
