import os
import sys
from pathlib import Path

def print_cron_schedule_instructions():
    python_bin = sys.executable
    project_dir = Path(__file__).resolve().parent.parent
    main_script = project_dir / "main.py"

    instructions = f"""
====================================================================
🛠️  AUTONOMOUS SCHEDULER & CRONTAB SETUP INSTRUCTIONS
====================================================================

Add the following lines to your crontab (`crontab -e`) to run the 
Autonomous Watchdog in the background:

# 1. Refresh GitHub Stack Dependencies profile every Sunday at midnight
0 0 * * 0 {python_bin} {main_script} sync > {project_dir}/sync.log 2>&1

# 2. Run Security Watchdog & Feed Ingestion every 30 minutes
*/30 * * * * {python_bin} {main_script} watchdog > {project_dir}/watchdog.log 2>&1

# 3. Generate & Dispatch Daily Digest every morning at 8:00 AM
0 8 * * * {python_bin} {main_script} digest > {project_dir}/digest.log 2>&1

====================================================================
"""
    print(instructions)
