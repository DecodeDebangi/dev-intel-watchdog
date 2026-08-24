import os
import json
import re
import time
import logging
from typing import Dict, Any, List, Tuple
from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.config import settings

logger = logging.getLogger("dev-intel-watchdog.analyzer")

def clean_html_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = clean.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', clean).strip()

def classify_report_category(title: str, text: str, action_required: bool) -> str:
    combined = f"{title.lower()} {text.lower()}"
    
    if action_required or any(k in combined for k in ["cve", "vulnerability", "security", "advisory", "patch", "exploit", "bug bounty", "malicious"]):
        return "Security & CVEs"
    elif any(k in combined for k in ["release", "version", "update", "package", "npm", "pypi", "python 3", "node.js"]):
        return "Package Releases"
    elif any(k in combined for k in ["ai", "llm", "copilot", "gpt", "model", "machine learning", "open source fund"]):
        return "AI & Ecosystem"
    elif any(k in combined for k in ["actions", "github", "docker", "cloud", "ci/cd", "workflow", "infrastructure"]):
        return "DevOps & Cloud"
    return "Package Releases"

class TechAnalysisResult(BaseModel):
    title: str
    category: str = "Package Releases"
    action_required: bool
    technical_summary: str
    affected_dependencies: List[str] = Field(default_factory=list)
    affected_repos_map: Dict[str, List[str]] = Field(default_factory=dict)
    affected_repo_counts: Dict[str, int] = Field(default_factory=dict)
    recommended_patch_commands: List[str] = Field(default_factory=list)
    consensus_weight: int = 1
    all_sources: List[str] = Field(default_factory=list)
    canonical_url: str = ""

class TechAnalyzer:
    def __init__(self, api_key: str = None, stack_path: str = None):
        self.api_key = api_key or settings.gemini_api_key
        self.stack_path = stack_path or settings.stack_context_path
        self.client = None
        self.quota_exhausted = False
        
        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")

    def load_stack_context(self) -> Dict[str, Any]:
        if os.path.exists(self.stack_path):
            try:
                with open(self.stack_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading stack context: {e}")
        return {
            "core_languages": ["JavaScript", "Python"],
            "active_dependencies": ["react", "express", "fastapi"],
            "dependency_repo_map": {"react": ["sample-app"], "express": ["sample-app"], "fastapi": ["sample-backend"]},
            "dependency_counts": {"react": 1, "express": 1, "fastapi": 1}
        }

    def _enrich_repo_metadata(self, affected_deps: List[str], stack: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
        repo_map = stack.get("dependency_repo_map", {})
        count_map = stack.get("dependency_counts", {})
        
        affected_repos: Dict[str, List[str]] = {}
        affected_counts: Dict[str, int] = {}
        
        for dep in affected_deps:
            dep_clean = dep.lower().strip()
            repos = repo_map.get(dep_clean, [])
            affected_repos[dep_clean] = repos
            affected_counts[dep_clean] = len(repos) if repos else count_map.get(dep_clean, 0)
            
        return affected_repos, affected_counts

    def fallback_rule_analysis(self, item: Any, stack: Dict[str, Any]) -> TechAnalysisResult:
        deps = stack.get("active_dependencies", [])
        title_clean = clean_html_text(item.title)
        text_clean = clean_html_text(item.text)
        combined = f"{title_clean.lower()} {text_clean.lower()}"
        
        matched_deps = []
        for dep in deps:
            if dep in combined:
                matched_deps.append(dep)
                
        is_security_alert = "cve" in combined or "vulnerability" in combined or "security" in combined or "exploit" in combined
        action_req = is_security_alert and len(matched_deps) > 0

        affected_repos, affected_counts = self._enrich_repo_metadata(matched_deps, stack)

        patch_cmds = []
        if action_req:
            for dep in matched_deps:
                patch_cmds.append(f"npm update {dep} # or pip install --upgrade {dep}")

        summary = text_clean[:280] + "..." if len(text_clean) > 280 else text_clean
        if action_req:
            summary = f"🚨 Vulnerability reported affecting active project dependencies ({', '.join(matched_deps)}). {summary}"

        category = classify_report_category(title_clean, text_clean, action_req)

        return TechAnalysisResult(
            title=title_clean,
            category=category,
            action_required=action_req,
            technical_summary=summary or title_clean,
            affected_dependencies=matched_deps,
            affected_repos_map=affected_repos,
            affected_repo_counts=affected_counts,
            recommended_patch_commands=patch_cmds,
            consensus_weight=getattr(item, "consensus_weight", 1),
            all_sources=getattr(item, "all_sources", [item.source if hasattr(item, "source") else "Feed"]),
            canonical_url=getattr(item, "canonical_url", getattr(item, "url", ""))
        )

    def analyze_item(self, item: Any) -> TechAnalysisResult:
        stack = self.load_stack_context()
        title_clean = clean_html_text(item.title)
        text_clean = clean_html_text(item.text)

        if not self.client or self.quota_exhausted:
            return self.fallback_rule_analysis(item, stack)

        consensus_wt = getattr(item, "consensus_weight", 1)
        sources = getattr(item, "all_sources", [getattr(item, "source", "Feed")])
        url = getattr(item, "canonical_url", getattr(item, "url", ""))

        system_instruction = f"""
        You are an Elite Principal Engineer and Security Architect.
        Evaluate the provided tech news/advisory item against the user's active codebase stack context:
        {json.dumps(stack)}

        Consensus weight across independent newsletter/feed sources: {consensus_wt}.
        Sources reporting this update: {sources}.

        Rules:
        1. Set action_required=true ONLY IF there is an active security vulnerability (CVE) or breaking API change affecting a package listed in the user's active_dependencies. Otherwise set action_required=false.
        2. Assign category to one of: 'Security & CVEs', 'Package Releases', 'DevOps & Cloud', 'AI & Ecosystem'.
        3. Provide concise technical_summary, list of affected_dependencies, and recommended_patch_commands.
        """

        prompt = f"Title: {title_clean}\nContent:\n{text_clean}"

        try:
            response = self.client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )

            data = json.loads(response.text)
            affected_deps = data.get("affected_dependencies", [])
            affected_repos, affected_counts = self._enrich_repo_metadata(affected_deps, stack)
            
            action_req = bool(data.get("action_required", False))
            cat = data.get("category", classify_report_category(title_clean, text_clean, action_req))

            return TechAnalysisResult(
                title=clean_html_text(data.get("title", title_clean)),
                category=cat,
                action_required=action_req,
                technical_summary=clean_html_text(data.get("technical_summary", text_clean[:250])),
                affected_dependencies=affected_deps,
                affected_repos_map=affected_repos,
                affected_repo_counts=affected_counts,
                recommended_patch_commands=data.get("recommended_patch_commands", []),
                consensus_weight=consensus_wt,
                all_sources=sources,
                canonical_url=url
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logger.warning("Gemini API daily quota limit reached. Switching to instant rule-based engine.")
                self.quota_exhausted = True
            else:
                logger.error(f"Gemini API error: {e}")
            return self.fallback_rule_analysis(item, stack)

def analyze_technical_content(item: Any) -> TechAnalysisResult:
    analyzer = TechAnalyzer()
    return analyzer.analyze_item(item)
