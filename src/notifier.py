import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
import requests
from typing import List

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.style import Style
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from src.config import settings
from src.analyzer import TechAnalysisResult

logger = logging.getLogger("dev-intel-watchdog.notifier")
console = Console() if RICH_AVAILABLE else None

class Notifier:
    def __init__(self, token: str = None, phone_id: str = None, recipient: str = None):
        self.token = token or settings.whatsapp_token
        self.phone_id = phone_id or settings.whatsapp_phone_id
        self.recipient = recipient or settings.my_phone_number
        
        self.digests_dir = Path(settings.database_path).parent / "digests"
        self.digests_dir.mkdir(parents=True, exist_ok=True)

    def _format_affected_stack_str(self, report: TechAnalysisResult) -> str:
        lines = []
        for dep in report.affected_dependencies:
            repos = report.affected_repos_map.get(dep, [])
            count = report.affected_repo_counts.get(dep, len(repos))
            if repos:
                repo_str = ", ".join(repos[:3]) + (f" +{len(repos)-3} more" if len(repos) > 3 else "")
                lines.append(f"`{dep}` (Used in {count} project{'s' if count != 1 else ''}: {repo_str})")
            elif count > 0:
                lines.append(f"`{dep}` (Used in {count} project{'s' if count != 1 else ''})")
            else:
                lines.append(f"`{dep}`")
        return " | ".join(lines)

    def log_terminal_report(self, report: TechAnalysisResult):
        if not RICH_AVAILABLE or not console:
            print(f"[{'URGENT' if report.action_required else 'ROUTINE'}] {report.title} (Weight: {report.consensus_weight})")
            print(f"Summary: {report.technical_summary}\n")
            return

        weight_str = f"🔥 Consensus Weight: {report.consensus_weight} sources" if report.consensus_weight > 1 else "1 Source"
        title_prefix = "🚨 URGENT PATCH REQUIRED 🚨" if report.action_required else "📋 Routine Tech Update"
        border_style = "bold red" if report.action_required else "bold cyan"

        body_md = f"**Sources:** {', '.join(report.all_sources)}\n\n"
        body_md += f"**Technical Summary:**\n{report.technical_summary}\n\n"
        
        if report.affected_dependencies:
            stack_formatted = self._format_affected_stack_str(report)
            body_md += f"**Affected Stack & Projects:** {stack_formatted}\n\n"
            
        if report.recommended_patch_commands:
            body_md += "**Recommended Fix:**\n```bash\n" + "\n".join(report.recommended_patch_commands) + "\n```\n"

        if report.canonical_url:
            body_md += f"[Read Original Article]({report.canonical_url})"

        panel = Panel(
            Markdown(body_md),
            title=f"[{border_style}]{title_prefix}: {report.title} ({weight_str})[/{border_style}]",
            border_style=border_style,
            expand=False
        )
        console.print(panel)

    def dispatch_whatsapp(self, report: TechAnalysisResult):
        weight_badge = f" 🔥 (Consensus Weight: {report.consensus_weight} sources)" if report.consensus_weight > 1 else ""
        prefix = "🚨 *URGENT PATCH REQUIRED* 🚨" if report.action_required else "📋 *Routine Briefing*"
        
        body = f"{prefix}{weight_badge}\n\n*{report.title}*\n\n{report.technical_summary}"
        
        if report.affected_dependencies:
            stack_formatted = self._format_affected_stack_str(report).replace("`", "")
            body += f"\n\n*Affected Stack & Projects:* {stack_formatted}"
            
        if report.recommended_patch_commands:
            body += f"\n*Patch Commands:*\n`" + " && ".join(report.recommended_patch_commands) + "`"

        if not self.token or not self.phone_id or not self.recipient:
            logger.info("WhatsApp tokens not fully configured. Outputting local test mode payload.")
            return

        try:
            url = f"https://graph.facebook.com/v17.0/{self.phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": self.recipient,
                "type": "text",
                "text": {"body": body}
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                logger.info(f"Successfully dispatched WhatsApp message for '{report.title}'!")
            else:
                logger.error(f"WhatsApp API Error {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Failed to dispatch WhatsApp alert: {e}")

    def save_digest_file(self, reports: List[TechAnalysisResult]):
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        file_path = self.digests_dir / f"digest_{today_str}.json"
        
        data = [report.model_dump() for report in reports]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        logger.info(f"Saved daily digest log containing {len(reports)} items to {file_path}")

def notify_report(report: TechAnalysisResult):
    notifier = Notifier()
    notifier.log_terminal_report(report)
    notifier.dispatch_whatsapp(report)
