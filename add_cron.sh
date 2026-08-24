#!/bin/bash

PYTHON_BIN="/Users/debangichoudhury/.gemini/antigravity/scratch/dev-intel-watchdog/venv/bin/python"
MAIN_PY="/Users/debangichoudhury/.gemini/antigravity/scratch/dev-intel-watchdog/main.py"
LOG_DIR="/Users/debangichoudhury/.gemini/antigravity/scratch/dev-intel-watchdog"

# Backup existing crontab
crontab -l > /tmp/my_crontab_backup 2>/dev/null || touch /tmp/my_crontab_backup

# Remove old watchdog entries if re-running
grep -v "dev-intel-watchdog/main.py" /tmp/my_crontab_backup > /tmp/new_crontab

# Add new schedule entries
echo "" >> /tmp/new_crontab
echo "# === Developer Intelligence & Security Watchdog Schedule ===" >> /tmp/new_crontab
echo "0 0 * * 0 $PYTHON_BIN $MAIN_PY sync > $LOG_DIR/sync.log 2>&1" >> /tmp/new_crontab
echo "*/30 * * * * $PYTHON_BIN $MAIN_PY watchdog > $LOG_DIR/watchdog.log 2>&1" >> /tmp/new_crontab
echo "0 8 * * * $PYTHON_BIN $MAIN_PY digest > $LOG_DIR/digest.log 2>&1" >> /tmp/new_crontab

# Install new crontab
crontab /tmp/new_crontab
rm /tmp/my_crontab_backup /tmp/new_crontab

echo "✅ Crontab schedule successfully added!"
crontab -l
