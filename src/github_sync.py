import os
import json
import base64
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Set, Any
import requests
from src.config import settings

logger = logging.getLogger("dev-intel-watchdog.github_sync")

UTILITY_NOISE_PATTERNS = [
    r"^eslint", r"^prettier", r"^@types/", r"^ts-", r"^typescript",
    r"^jest", r"^vitest", r"^pyobjc", r"^standard-", r"^hardhat-",
    r"^solhint", r"^rimraf", r"^nodemon", r"^husky", r"^commitlint",
    r"^babel", r"^webpack", r"^postcss", r"^autoprefixer", r"^tailwindcss-animate"
]

class GitHubStackProfiler:
    def __init__(self, token: str = None, stack_path: str = None):
        self.token = token or settings.github_access_token
        self.stack_path = stack_path or settings.stack_context_path

    def load_existing_profile(self) -> dict:
        if os.path.exists(self.stack_path):
            try:
                with open(self.stack_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "custom_dependencies" not in data:
                        data["custom_dependencies"] = []
                    if "excluded_dependencies" not in data:
                        data["excluded_dependencies"] = []
                    if "feed_preferences" not in data:
                        data["feed_preferences"] = {}
                    return data
            except Exception as e:
                logger.error(f"Error reading stack profile at {self.stack_path}: {e}")
        return {
            "source": "Default fallback context",
            "core_languages": ["TypeScript", "JavaScript", "Python"],
            "github_dependencies": ["react", "react-dom", "next", "express", "fastapi", "pydantic"],
            "custom_dependencies": [],
            "excluded_dependencies": [],
            "active_dependencies": ["react", "react-dom", "next", "express", "fastapi", "pydantic"],
            "dependency_repo_map": {
                "react": ["default-app"],
                "next": ["default-app"],
                "fastapi": ["default-backend"]
            },
            "dependency_counts": {
                "react": 1,
                "next": 1,
                "fastapi": 1
            },
            "feed_preferences": {},
            "last_synced": None
        }

    def _recalculate_active_dependencies(self, profile: dict) -> dict:
        github_deps = set(profile.get("github_dependencies", []))
        custom_deps = set(profile.get("custom_dependencies", []))
        excluded_deps = set(profile.get("excluded_dependencies", []))

        merged = (github_deps | custom_deps) - excluded_deps
        profile["active_dependencies"] = sorted(list(merged))
        
        repo_map = profile.get("dependency_repo_map", {})
        counts = profile.get("dependency_counts", {})

        for custom in custom_deps:
            if custom not in repo_map:
                repo_map[custom] = ["Manual User Add"]
                counts[custom] = 1

        profile["dependency_repo_map"] = repo_map
        profile["dependency_counts"] = counts

        with open(self.stack_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

        return profile

    def update_feed_preferences(self, prefs: Dict[str, bool]) -> dict:
        profile = self.load_existing_profile()
        current_prefs = profile.get("feed_preferences", {})
        current_prefs.update(prefs)
        profile["feed_preferences"] = current_prefs
        return self._recalculate_active_dependencies(profile)

    def reset_feed_preferences(self) -> dict:
        profile = self.load_existing_profile()
        profile["feed_preferences"] = {}
        return self._recalculate_active_dependencies(profile)

    def add_custom_dependency(self, dep_name: str) -> dict:
        dep_clean = dep_name.lower().strip()
        if not dep_clean:
            return self.load_existing_profile()

        profile = self.load_existing_profile()
        customs = set(profile.get("custom_dependencies", []))
        excluded = set(profile.get("excluded_dependencies", []))

        customs.add(dep_clean)
        excluded.discard(dep_clean)

        profile["custom_dependencies"] = sorted(list(customs))
        profile["excluded_dependencies"] = sorted(list(excluded))

        return self._recalculate_active_dependencies(profile)

    def remove_dependency(self, dep_name: str) -> dict:
        dep_clean = dep_name.lower().strip()
        if not dep_clean:
            return self.load_existing_profile()

        profile = self.load_existing_profile()
        excluded = set(profile.get("excluded_dependencies", []))
        customs = set(profile.get("custom_dependencies", []))

        excluded.add(dep_clean)
        customs.discard(dep_clean)

        profile["excluded_dependencies"] = sorted(list(excluded))
        profile["custom_dependencies"] = sorted(list(customs))

        return self._recalculate_active_dependencies(profile)

    def bulk_remove_dependencies(self, dep_names: List[str]) -> dict:
        profile = self.load_existing_profile()
        excluded = set(profile.get("excluded_dependencies", []))
        customs = set(profile.get("custom_dependencies", []))

        for name in dep_names:
            dep_clean = name.lower().strip()
            if dep_clean:
                excluded.add(dep_clean)
                customs.discard(dep_clean)

        profile["excluded_dependencies"] = sorted(list(excluded))
        profile["custom_dependencies"] = sorted(list(customs))

        return self._recalculate_active_dependencies(profile)

    def bulk_restore_dependencies(self, dep_names: List[str]) -> dict:
        profile = self.load_existing_profile()
        excluded = set(profile.get("excluded_dependencies", []))

        for name in dep_names:
            dep_clean = name.lower().strip()
            if dep_clean:
                excluded.discard(dep_clean)

        profile["excluded_dependencies"] = sorted(list(excluded))
        return self._recalculate_active_dependencies(profile)

    def clean_utility_noise(self) -> dict:
        profile = self.load_existing_profile()
        active_deps = profile.get("active_dependencies", [])
        excluded = set(profile.get("excluded_dependencies", []))

        noise_count = 0
        for dep in active_deps:
            dep_clean = dep.lower().strip()
            for pattern in UTILITY_NOISE_PATTERNS:
                if re.search(pattern, dep_clean):
                    excluded.add(dep_clean)
                    noise_count += 1
                    break

        profile["excluded_dependencies"] = sorted(list(excluded))
        logger.info(f"Cleaned {noise_count} dev/utility noise packages.")
        return self._recalculate_active_dependencies(profile)

    def restore_dependency(self, dep_name: str) -> dict:
        return self.bulk_restore_dependencies([dep_name])

    def sync_profile(self) -> dict:
        existing = self.load_existing_profile()
        custom_deps = set(existing.get("custom_dependencies", []))
        excluded_deps = set(existing.get("excluded_dependencies", []))
        feed_prefs = existing.get("feed_preferences", {})

        if not self.token:
            logger.warning("GITHUB_ACCESS_TOKEN not configured. Utilizing existing stack context.")
            return self.load_existing_profile()

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        try:
            res = requests.get(
                "https://api.github.com/user/repos?per_page=100&sort=updated",
                headers=headers,
                timeout=10
            )
            if res.status_code != 200:
                logger.error(f"Failed to fetch GitHub repos. Status Code: {res.status_code}")
                return self.load_existing_profile()

            repos = res.json()
            languages: Set[str] = set()
            dependency_repo_map: Dict[str, Set[str]] = {}

            for repo in repos:
                if repo.get("fork"):
                    continue
                
                lang = repo.get("language")
                if lang:
                    languages.add(lang)

                owner = repo["owner"]["login"]
                repo_name = repo["name"]

                def add_dependency(dep_raw: str, repository: str):
                    clean_dep = dep_raw.split("/")[-1].replace("@types/", "").lower().strip()
                    if not clean_dep:
                        return
                    if clean_dep not in dependency_repo_map:
                        dependency_repo_map[clean_dep] = set()
                    dependency_repo_map[clean_dep].add(repository)

                pkg_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/package.json"
                pkg_res = requests.get(pkg_url, headers=headers, timeout=5)
                if pkg_res.status_code == 200:
                    try:
                        content_str = base64.b64decode(pkg_res.json()["content"]).decode("utf-8")
                        pkg_data = json.loads(content_str)
                        all_deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                        for dep_name in all_deps.keys():
                            add_dependency(dep_name, repo_name)
                    except Exception as e:
                        logger.debug(f"Error parsing package.json for {repo_name}: {e}")

                req_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/requirements.txt"
                req_res = requests.get(req_url, headers=headers, timeout=5)
                if req_res.status_code == 200:
                    try:
                        content_str = base64.b64decode(req_res.json()["content"]).decode("utf-8")
                        for line in content_str.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip()
                                if pkg:
                                    add_dependency(pkg, repo_name)
                    except Exception as e:
                        logger.debug(f"Error parsing requirements.txt for {repo_name}: {e}")

            for custom in custom_deps:
                if custom not in dependency_repo_map:
                    dependency_repo_map[custom] = {"Manual User Add"}

            github_deps_set = set(dependency_repo_map.keys())

            formatted_repo_map: Dict[str, List[str]] = {
                dep: sorted(list(repos_set)) for dep, repos_set in dependency_repo_map.items()
            }
            dependency_counts: Dict[str, int] = {
                dep: len(repos_list) for dep, repos_list in formatted_repo_map.items()
            }

            profile = {
                "source": "Auto-synced from GitHub REST API & User Custom Settings",
                "core_languages": sorted(list(languages)),
                "github_dependencies": sorted(list(github_deps_set)),
                "custom_dependencies": sorted(list(custom_deps)),
                "excluded_dependencies": sorted(list(excluded_deps)),
                "dependency_repo_map": formatted_repo_map,
                "dependency_counts": dependency_counts,
                "feed_preferences": feed_prefs,
                "last_synced": datetime.now(timezone.utc).isoformat()
            }

            return self._recalculate_active_dependencies(profile)

        except Exception as e:
            logger.error(f"Error during GitHub profile synchronization: {e}")
            return self.load_existing_profile()

def fetch_github_stack_profile() -> dict:
    profiler = GitHubStackProfiler()
    return profiler.sync_profile()

def add_custom_dependency(dep_name: str) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.add_custom_dependency(dep_name)

def remove_dependency(dep_name: str) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.remove_dependency(dep_name)

def bulk_remove_dependencies(dep_names: List[str]) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.bulk_remove_dependencies(dep_names)

def restore_dependency(dep_name: str) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.restore_dependency(dep_name)

def bulk_restore_dependencies(dep_names: List[str]) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.bulk_restore_dependencies(dep_names)

def clean_utility_noise() -> dict:
    profiler = GitHubStackProfiler()
    return profiler.clean_utility_noise()

def update_feed_preferences(prefs: Dict[str, bool]) -> dict:
    profiler = GitHubStackProfiler()
    return profiler.update_feed_preferences(prefs)

def reset_feed_preferences() -> dict:
    profiler = GitHubStackProfiler()
    return profiler.reset_feed_preferences()
